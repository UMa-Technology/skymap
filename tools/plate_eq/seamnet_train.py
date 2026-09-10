"""Train SeamNet v2: on-the-fly random crops (no memorizable pool) + prefetch thread.
Run:  python seamnet_train.py [steps]   (default 9000)"""
import os, sys, time, threading, queue
import numpy as np
import torch
from seamnet_common import (SC, SZ, load_state, load_labels, draw_crop, inject,
                            edge_maps, net_input)
from seamnet_model import UNet

OUT = SC + "/seamnet"
os.makedirs(OUT, exist_ok=True)
STEPS = int(sys.argv[1]) if len(sys.argv) > 1 else 9000
BATCH = 16
NVAL = 256
DEV = torch.device("mps" if torch.backends.mps.is_available() else "cpu")

R, G, B, GB = load_state()
LABR, LABB = load_labels()
print("state+labels loaded, device:", DEV, flush=True)


def make_sample(rng):
    img, a, bb, gc = draw_crop(rng, R, G, B, GB, LABR, LABB)
    x, A = inject(img, a, bb, gc, rng)
    er, eb = edge_maps(a, bb)
    inp = net_input(x, er, eb)
    L = 0.299 * img[0] + 0.587 * img[1] + 0.114 * img[2]
    w = np.maximum(1.0 / (1.0 + L / 30.0), 0.3)          # floor: bright MW still counts
    if rng.random() < 0.5:
        inp, A, w = inp[:, :, ::-1].copy(), A[:, :, ::-1].copy(), w[:, ::-1].copy()
    return inp, A, w[None], float(np.median(np.abs(gc)))


def make_batch(rng):
    xs, ys, ws = [], [], []
    for _ in range(BATCH):
        inp, A, w, _ = make_sample(rng)
        xs.append(inp); ys.append(A); ws.append(w)
    return (torch.from_numpy(np.stack(xs)), torch.from_numpy(np.stack(ys)),
            torch.from_numpy(np.stack(ws)))


# prefetch worker keeps the GPU fed while CPU generates the next batches
Q = queue.Queue(maxsize=6)
def worker(seed):
    wrng = np.random.default_rng(seed)
    while True:
        Q.put(make_batch(wrng))
threading.Thread(target=worker, args=(42,), daemon=True).start()

# fixed deterministic val set (fresh sky positions each run seed, but stable in-run)
vrng = np.random.default_rng(1234)
VX, VY, VW, VB = [], [], [], []
for i in range(NVAL):
    inp, A, w, mb = make_sample(vrng)
    VX.append(inp); VY.append(A); VW.append(w); VB.append(mb)
VX = torch.from_numpy(np.stack(VX)); VY = torch.from_numpy(np.stack(VY))
VW = torch.from_numpy(np.stack(VW)); VB = np.array(VB)
INBAND = VB < 15.0
print("val set ready: %d crops (%d in-band)" % (NVAL, int(INBAND.sum())), flush=True)

net = UNet().to(DEV)
print("params: %.1fM" % (sum(p.numel() for p in net.parameters()) / 1e6), flush=True)
opt = torch.optim.AdamW(net.parameters(), lr=3e-4, weight_decay=1e-4)
sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, STEPS, eta_min=3e-5)


def wl1(pred, y, w):
    return (w * (pred - y).abs()).mean() / w.mean()


@torch.no_grad()
def validate():
    net.eval()
    se = np.zeros(NVAL); sa = np.zeros(NVAL); sw = np.zeros(NVAL)
    for k in range(0, NVAL, 8):
        x = VX[k:k+8].to(DEV); y = VY[k:k+8].to(DEV); w = VW[k:k+8].to(DEV)
        p = net(x)
        se[k:k+8] = (w * (p - y) ** 2).sum((1, 2, 3)).cpu().numpy()
        sa[k:k+8] = (w * y ** 2).sum((1, 2, 3)).cpu().numpy()
        sw[k:k+8] = w.sum((1, 2, 3)).cpu().numpy() * 3
    net.train()
    rms = (se.sum() / sw.sum()) ** 0.5
    arms = (sa.sum() / sw.sum()) ** 0.5
    rmsb = (se[INBAND].sum() / sw[INBAND].sum()) ** 0.5
    armsb = (sa[INBAND].sum() / sw[INBAND].sum()) ** 0.5
    return rms, arms, rmsb, armsb


best = 1e9
t0 = time.time()
ema = None
for step in range(1, STEPS + 1):
    x, y, w = Q.get()
    x, y, w = x.to(DEV), y.to(DEV), w.to(DEV)
    loss = wl1(net(x), y, w)
    opt.zero_grad(set_to_none=True)
    loss.backward()
    torch.nn.utils.clip_grad_norm_(net.parameters(), 1.0)
    opt.step(); sched.step()
    if step % 100 == 0:
        l = float(loss.detach())
        ema = l if ema is None else 0.9 * ema + 0.1 * l
        print("step %d loss %.4f ema %.4f lr %.1e %ds" %
              (step, l, ema, sched.get_last_lr()[0], int(time.time() - t0)), flush=True)
    if step % 500 == 0 or step == STEPS:
        rms, arms, rmsb, armsb = validate()
        print("VAL step %d residRMS %.4f/%.4f ratio %.3f | in-band %.4f/%.4f ratio %.3f" %
              (step, rms, arms, rms / arms, rmsb, armsb, rmsb / armsb), flush=True)
        torch.save(net.state_dict(), OUT + "/ckpt_last.pt")
        if rms < best:
            best = rms
            torch.save(net.state_dict(), OUT + "/ckpt_best.pt")
print("TRAIN DONE best residRMS %.4f (%ds)" % (best, int(time.time() - t0)), flush=True)
