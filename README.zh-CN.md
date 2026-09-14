# SkyMap

[English](README.md) | 简体中文

SkyMap 是一个离线、可嵌入的星图 Web 层，基于
[Stellarium Web Engine](https://github.com/Stellarium/stellarium-web-engine)
的一个 fork：C 语言天文馆引擎编译成 WebAssembly，由一个 Vue 3 页面驱动，再通过
一层很薄的 JavaScript 桥与宿主通信。星表数据（恒星、深空天体、DSS 巡天、地景、
翻译）随仓库一起提供，运行期不联网。

本仓库是**基座**：引擎、Web 层、数据与构建工具。宿主应用（Flutter App、原生
WebView）只消费孤儿分支 `dist` 上发布的单一构建产物 `dist.zip`，它们不在本仓库内。

## 仓库结构

| 路径 | 内容 |
|---|---|
| `src/`、`data/`、`ext_src/`、`SConstruct` | C 引擎及其构建 |
| `build-engine.sh` | 把引擎编译成 WASM/JS 并安装进 Web 层 |
| `apps/skymap-web/` | Web 层（Vite + Vue 3）。JS 桥的契约见 `USAGE.md` |
| `apps/skydata/` | Web 层提供的星表数据（`apps/skymap-web/public/skydata` 是指向它的符号链接） |
| `tools/` | 数据管线（星表、翻译、字体、巡天清理）与 `make-dist-zip.sh` |
| `tools/release.sh` | 打发版标签，并把 `dist.zip` 发布到孤儿分支 `dist`（git-lfs） |
| `tools/sync-github.sh` | 把 `github` 分支快进后推到 GitHub 镜像 |
| `.github/workflows/` | CI 构建门禁；标签触发的 `dist.zip` 发布 |

`dev_docs/` 与 `docs/` 已被忽略：内部文档在一个私有仓库里，开发机上以符号链接挂入。

分支：`develop`（日常开发）→ `main`（稳定）→ `github`（由 `tools/sync-github.sh`
推送到 GitHub `main` 的快照）。孤儿分支 `dist` 只存放发版产物。

## 构建引擎

前置：在当前 shell 中激活 [emscripten SDK](https://emscripten.org) **6.0.2**
（`source ~/emsdk/emsdk_env.sh`），以及 `scons`（`pip install scons`）。

```bash
./build-engine.sh          # release 构建；多余参数透传给 scons（例如 mode=debug）
```

它会写出 `apps/skymap-web/src/assets/js/stellarium-web-engine.{js,wasm}`
（不入库）。改动 `src/` 下任何文件后都要重跑。

## 构建 Web 层

前置：Node 24（见 `apps/skymap-web/.nvmrc`）；Python 3 并装好 `fonttools` 与
`brotli`（`pip install fonttools brotli`，图标子集化要用）。

```bash
cd apps/skymap-web
npm ci
npm run dev        # http://localhost:8080，带热更新
npm run build      # dist/ → dist.zip + dist.zip.sha256 + dist.zip.json
npx vitest run     # 单元测试
npm run lint
```

`npm run build` 结束后会跑 `tools/make-dist-zip.sh`，产出逐字节可复现的
`dist.zip`（归一化修改时间与权限位），并在旁边生成两个 sidecar：SHA-256，以及一份
记录了提交、工作树是否脏、`dist/` 是否陈旧、引擎 WASM 哈希与版本号的 JSON。

打包脚本的 Python 测试：

```bash
python3 -m pytest tools/tests/test_make_dist_zip.py tools/tests/test_install_dist.py
```

`tools/tests/` 下的 DSS 巡天清理套件需要 `tools/requirements-clean-dss.txt` 里的
科学计算栈（Python 3.11），CI 不跑它。

## 发版与握手

`tools/release.sh vX.Y.Z`（在干净的 `main` 上运行）会把版本号烙进 Web 层构建、给
该提交打上 `vX.Y.Z` 标签，并把 `dist.zip`、`dist.zip.sha256`、`dist.zip.json` 提交
到孤儿分支 `dist`（git-lfs），打上 `dist/vX.Y.Z` 标签。宿主应用用
`git clone --depth 1 --branch dist/vX.Y.Z` 取某一版（它们的 `bin/skymap_dist.py`
就是这么做的，并会校验 SHA-256）；宿主永远不自己构建 Web 层。在 GitHub 镜像上，
推送 `v*` 标签还会把同样这三个文件挂到一个 GitHub Release 上
（`.github/workflows/release.yml`）。

每份构建都自带身份：

- 页面上的 `window.SkymapBase = { version, protocol }`，同一个对象也作为 `base`
  字段挂在发给宿主的每一条 `initProgress` 消息上；
- `dist.zip` 内的 `skymap-base.json`（内容相同）；
- `dist.zip.json` 里的 `"version"`。

`version` 是 git 标签（本地构建则是 `git describe` 的输出）。
`protocol`（`apps/skymap-web/src/protocol.js`）只在**已有**的桥接 action、
`getState` 字段或下行消息改变语义或被删除时才递增；新增 action 不递增。宿主应当
要求 `protocol` 精确相等，并同时要求一个最低版本号。

## 许可

SkyMap 以 **GNU Affero 通用公共许可证第 3 版**（AGPL-3.0）授权，见 `LICENSE`。
它派生自 Stellarium Web Engine，Copyright (c) Stellarium Labs SRL，fork 自上游
合并基点 `be43d6436`（2026-05-09）；此后不再合并上游改动。本 fork 内的改动
Copyright (C) 2026 Suzhou UMa Technology Co., Ltd，摘要见 `CHANGELOG.md`。

数据来源与致谢：

- DSS 彩色巡天：Digitized Sky Survey，STScI/NASA；上色与 HEALPix 切片由 CDS 完成
  （`apps/skydata/surveys/dss/properties`）。
- 月球纹理由 Oleg Pluton 提供（CC BY 4.0）；太阳纹理来自 Sky-Watcher。
- 星空文化（skycultures）：Western 来自 [@氕氘氚Star](https://github.com/LHF-CN/)。
- 字体：见 `tools/.fontcache/LICENSES.md`。

## 鸣谢

- [@氕氘氚Star](https://github.com/LHF-CN/)
