"""Star-removal ResUNet (torch, MPS-safe).

Design locked by the 11-source study:
  - subtractive head: out = in - relu(r)  (can only darken; r = star layer)
  - GroupNorm (BatchNorm banned: residual target ~0.4-1.2% FS vs BN stat drift)
  - reflect padding everywhere (patch-border ringing)
  - region-weighted L1: weight 1 outside star mask (brightness consistency on
    the preserve class), 1+W_STAR*softmask inside
Input/output space: dn/127.5 - 1.
"""
import torch
import torch.nn as nn
import torch.nn.functional as F


def conv3(i, o):
    return nn.Conv2d(i, o, 3, padding=1, padding_mode='reflect')


class Block(nn.Module):
    def __init__(self, i, o):
        super().__init__()
        self.c1 = conv3(i, o); self.n1 = nn.GroupNorm(8, o)
        self.c2 = conv3(o, o); self.n2 = nn.GroupNorm(8, o)
        self.skip = nn.Conv2d(i, o, 1) if i != o else nn.Identity()

    def forward(self, x):
        h = F.silu(self.n1(self.c1(x)))
        h = self.n2(self.c2(h))
        return F.silu(h + self.skip(x))


class StarNet8(nn.Module):
    def __init__(self, widths=(32, 64, 128, 256)):
        super().__init__()
        w = widths
        self.stem = Block(3, w[0])
        self.down = nn.ModuleList()
        self.enc = nn.ModuleList()
        for i in range(len(w) - 1):
            self.down.append(nn.Conv2d(w[i], w[i + 1], 3, stride=2, padding=1))
            self.enc.append(Block(w[i + 1], w[i + 1]))
        self.dec = nn.ModuleList()
        for i in range(len(w) - 1, 0, -1):
            self.dec.append(Block(w[i] + w[i - 1], w[i - 1]))
        self.head = nn.Conv2d(w[0], 3, 3, padding=1, padding_mode='reflect')
        nn.init.zeros_(self.head.bias)

    def forward(self, x):
        skips = []
        h = self.stem(x)
        for dn, enc in zip(self.down, self.enc):
            skips.append(h)
            h = enc(F.silu(dn(h)))
        for dec in self.dec:
            s = skips.pop()
            h = F.interpolate(h, size=s.shape[-2:], mode='bilinear', align_corners=False)
            h = dec(torch.cat([h, s], 1))
        r = F.relu(self.head(h))          # non-negative star layer
        return x - r, r


def loss_fn(out, target, star_mask, w_star=4.0):
    """region-weighted L1; star_mask (B,1,H,W) soft in [0,1]."""
    w = 1.0 + w_star * star_mask
    return (w * (out - target).abs()).mean(), {
        'l1_star': ((out - target).abs() * star_mask).sum() / star_mask.sum().clamp(min=1.0),
        'l1_bg': ((out - target).abs() * (1 - star_mask)).sum() / (1 - star_mask).sum().clamp(min=1.0),
    }


if __name__ == "__main__":
    m = StarNet8()
    n = sum(p.numel() for p in m.parameters())
    x = torch.randn(2, 3, 256, 256)
    y, r = m(x)
    print(f"params {n/1e6:.2f}M out {tuple(y.shape)} residual>=0: {bool((r>=0).all())}")
    print("only-darken check:", bool((y <= x + 1e-6).all()))
