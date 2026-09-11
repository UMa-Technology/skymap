// SkyMap - Copyright (C) 2026 Suzhou UMa Technology Co., Ltd
//
// This program is licensed under the terms of the GNU AGPL v3.
// The terms of the AGPL v3 license can be found in the main directory of this
// repository.

// Development-only switch: `?webgui=1` mounts the full web GUI (toolbar,
// search, settings, bottom bar) instead of the bare embedded overlay.
// Hosts never pass it; the shipped page behaves exactly as before.
export function wantsWebGui (search) {
  return new URLSearchParams(search || '').get('webgui') === '1'
}
