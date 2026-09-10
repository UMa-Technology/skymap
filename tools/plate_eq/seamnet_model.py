"""SeamNet U-Net model (8ch in -> 3ch artifact field in DN)."""
import torch
import torch.nn as nn


class Block(nn.Module):
    def __init__(s, ci, co):
        super().__init__()
        s.f = nn.Sequential(
            nn.Conv2d(ci, co, 3, padding=1), nn.GroupNorm(8, co), nn.SiLU(),
            nn.Conv2d(co, co, 3, padding=1), nn.GroupNorm(8, co), nn.SiLU())

    def forward(s, x):
        return s.f(x)


class UNet(nn.Module):
    def __init__(s, ci=8, co=3, ch=(48, 96, 192, 384)):
        super().__init__()
        s.e = nn.ModuleList()
        c = ci
        for k in ch:
            s.e.append(Block(c, k)); c = k
        s.pool = nn.MaxPool2d(2)
        s.mid = Block(ch[-1], ch[-1] * 2)
        s.u = nn.ModuleList(); s.d = nn.ModuleList()
        c = ch[-1] * 2
        for k in reversed(ch):
            s.u.append(nn.ConvTranspose2d(c, k, 2, 2))
            s.d.append(Block(k * 2, k)); c = k
        s.out = nn.Conv2d(c, co, 1)

    def forward(s, x):
        skips = []
        for e in s.e:
            x = e(x); skips.append(x); x = s.pool(x)
        x = s.mid(x)
        for u, d, sk in zip(s.u, s.d, reversed(skips)):
            x = u(x); x = d(torch.cat([x, sk], 1))
        return s.out(x)
