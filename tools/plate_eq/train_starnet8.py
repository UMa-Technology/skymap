"""Train the star-removal net on synthetic pairs (MPS).

Usage: python train_starnet8.py [steps] [resume_ckpt]
Dumps: starnet8/ckpt_*.pt, starnet8/val_*.png (input|output|target|residual grids),
metrics printed every 50 steps (l1_star should fall hard; l1_bg must stay ~0).
"""
import os, sys, time, threading, queue
import numpy as np, cv2, torch
SC = os.environ.get("SCRATCH", os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SC)
from synth_star_pairs import PairGen
from starnet8 import StarNet8, loss_fn

STEPS = int(sys.argv[1]) if len(sys.argv) > 1 else 6000
RESUME = sys.argv[2] if len(sys.argv) > 2 else None
BATCH = 8
LR = 2e-4
OUT = os.path.join(SC, "starnet8")
os.makedirs(OUT, exist_ok=True)

dev = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
print("device:", dev, flush=True)

def to_net(x):  # dn -> [-1,1]
    return x / 127.5 - 1.0

gen_train = PairGen(SC + "/starcut_lib.npz", seed=42)
gen_val = PairGen(SC + "/starcut_lib.npz", seed=777)

def make_batch(g, n=BATCH):
    xs, ys, ms = [], [], []
    for _ in range(n):
        i, t, m = g.sample()
        xs.append(i); ys.append(t); ms.append(m)
    x = torch.from_numpy(to_net(np.stack(xs))).permute(0, 3, 1, 2).float()
    y = torch.from_numpy(to_net(np.stack(ys))).permute(0, 3, 1, 2).float()
    m = torch.from_numpy(np.stack(ms))[:, None].float()
    return x, y, m

VAL = [make_batch(gen_val) for _ in range(4)]

q = queue.Queue(maxsize=6)
stop = threading.Event()
def producer():
    while not stop.is_set():
        try:
            q.put(make_batch(gen_train), timeout=2)
        except queue.Full:
            continue
for _ in range(2):
    threading.Thread(target=producer, daemon=True).start()

model = StarNet8().to(dev)
opt = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=1e-4)
sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=STEPS, eta_min=LR * 0.1)
step0 = 0
if RESUME:
    ck = torch.load(RESUME, map_location=dev)
    model.load_state_dict(ck['model']); opt.load_state_dict(ck['opt'])
    step0 = ck['step']
    print("resumed from", RESUME, "step", step0, flush=True)

def dump_val(step):
    model.eval()
    rows = []
    with torch.no_grad():
        x, y, m = VAL[0]
        out, r = model(x.to(dev))
        out = out.cpu(); r = r.cpu()
        for i in range(min(4, x.shape[0])):
            def img(t):
                a = ((t.permute(1, 2, 0).numpy() + 1) * 127.5).clip(0, 255).astype(np.uint8)
                return a
            res = (r[i].permute(1, 2, 0).numpy() * 127.5 * 4).clip(0, 255).astype(np.uint8)
            rows.append(np.hstack([img(x[i]), img(out[i]), img(y[i]), res]))
    cv2.imwrite(os.path.join(OUT, f"val_{step:06d}.png"), np.vstack(rows)[:, :, ::-1])
    model.train()

best = 1e9
t0 = time.time()
model.train()
for step in range(step0, STEPS):
    x, y, m = q.get()
    x, y, m = x.to(dev), y.to(dev), m.to(dev)
    out, r = model(x)
    loss, parts = loss_fn(out, y, m)
    opt.zero_grad(set_to_none=True)
    loss.backward()
    torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
    opt.step(); sched.step()
    if (step + 1) % 50 == 0:
        with torch.no_grad():
            vls, vbs = [], []
            for vx, vy, vm in VAL:
                vo, _ = model(vx.to(dev))
                _, vp = loss_fn(vo, vy.to(dev), vm.to(dev))
                vls.append(float(vp['l1_star'])); vbs.append(float(vp['l1_bg']))
        # report in DN units (x127.5)
        print("step %5d loss %.5f | train l1_star %.2f DN l1_bg %.3f DN | val star %.2f bg %.3f | %.2fs/step" %
              (step + 1, float(loss), float(parts['l1_star']) * 127.5, float(parts['l1_bg']) * 127.5,
               np.mean(vls) * 127.5, np.mean(vbs) * 127.5, (time.time() - t0) / 50), flush=True)
        t0 = time.time()
        vscore = np.mean(vls) + 3 * np.mean(vbs)
        if vscore < best:
            best = vscore
            torch.save({'model': model.state_dict(), 'opt': opt.state_dict(), 'step': step + 1},
                       os.path.join(OUT, "ckpt_best.pt"))
    if (step + 1) % 500 == 0:
        dump_val(step + 1)
        torch.save({'model': model.state_dict(), 'opt': opt.state_dict(), 'step': step + 1},
                   os.path.join(OUT, "ckpt_last.pt"))
stop.set()
print("DONE best", best, flush=True)
