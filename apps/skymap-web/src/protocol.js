// SkyMap - Copyright (C) 2026 Suzhou UMa Technology Co., Ltd
//
// This program is licensed under the terms of the GNU AGPL v3.
// The terms of the AGPL v3 license can be found in the main directory of this
// repository.

// Wire-protocol number of the web layer. Bump it when an existing bridge
// action, getState key or inbound message changes meaning or is removed.
// Adding actions does not bump it: hosts guard against missing actions with a
// minimum base version instead (see README "Releases and the handshake").
export const PROTOCOL = 1

// The identity object exposed as window.SkymapBase and attached as `base` to
// every 'initProgress' message. `version` is the git tag baked in at build
// time (vite.config.mjs); local builds without a tag report '0.0.0-local'.
export function skymapBase (version) {
  return Object.freeze({
    version: version ? String(version) : '0.0.0-local',
    protocol: PROTOCOL
  })
}
