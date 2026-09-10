
-include src/private/Makefile

.PHONY: js
js:
	emscons scons -j8 mode=release

.PHONY: js-debug
js-debug:
	emscons scons -j8 mode=debug

.PHONY: js-prof
js-prof:
	emscons scons -j8 mode=profile

.PHONY: js-es6
js-es6:
	emscons scons -j8 mode=release es6=1
  
.PHONY: js-es6-debug
js-es6-debug:
	emscons scons -j8 mode=debug es6=1

.PHONY: js-es6-prof
js-es6-prof:
	emscons scons -j8 mode=profile es6=1

# Make the doc using natualdocs.  On debian, we only have an old version
# of naturaldocs available, where it is not possible to exclude files by
# pattern.  I don't want to parse the C files (only the headers), so for
# the moment I use a tmp file to copy the sources and remove the C files.
# It's a bit ugly.
.PHONY: doc
doc:
	rm -rf /tmp/swe_src
	cp -rf src /tmp/swe_src
	./build/stellarium-web-engine --gen-doc > /tmp/swe_src/generated-doc.h
	find /tmp/swe_src -name '*.c' | xargs rm
	mkdir -p build/doc/ndconfig
	naturaldocs -nag -i /tmp/swe_src -o html doc -p build/doc/ndconfig

clean:
	scons -c

# 从已构建的 dist/ 生成可复现的 dist.zip（allowlist + 归一 mtime）。
# 产物 dist.zip + 同名 .sha256 / .json sidecar；装进 App 仓用 tools/install-dist.sh <app-root>。
#
# 这里刻意不写构建依赖：打包和构建是两件事，有时就是要打一份旧快照。
# 但 dist/ 陈旧时脚本会在 stderr 上大声警告，看到警告再决定要不要先重建：
#   前端改动  → cd apps/skymap-web && npx vite build
#   引擎 C 改动 → ./build-engine.sh（重编 WASM）
# 两棵树都动过就两个都要跑，只重建前端会得到半套产物。
.PHONY: dist-zip
dist-zip:
	tools/make-dist-zip.sh
