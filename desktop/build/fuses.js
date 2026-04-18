// electron-builder afterPack hook — flips Electron Fuses on the packed binary.
//
// Fuses are compile-time booleans baked into the Electron executable. Flipping
// them post-pack removes attack primitives without needing a custom Electron
// build. Each fuse below closes a documented post-EOL CVE class or RCE vector.
//
// References:
//   https://www.electronjs.org/docs/latest/tutorial/fuses
//   https://github.com/electron/fuses

const { flipFuses, FuseVersion, FuseV1Options } = require('@electron/fuses');
const path = require('path');

module.exports = async function afterPack(context) {
  const { electronPlatformName, appOutDir, packager } = context;

  // Resolve the path to the packed Electron executable.
  const exeName =
    electronPlatformName === 'darwin'
      ? `${packager.appInfo.productFilename}.app`
      : electronPlatformName === 'win32'
        ? `${packager.appInfo.productFilename}.exe`
        : packager.executableName || packager.appInfo.productFilename;
  const exePath = path.join(appOutDir, exeName);

  await flipFuses(exePath, {
    version: FuseVersion.V1,

    // Disable the `ELECTRON_RUN_AS_NODE` env var. Without this, an attacker
    // who can set env on the victim's session can launch the app as a bare
    // Node interpreter and run arbitrary JS with the app's Authenticode
    // trust. Closes a post-sign RCE path.
    [FuseV1Options.RunAsNode]: false,

    // Encrypt cookies at rest via OS-level keychain.
    [FuseV1Options.EnableCookieEncryption]: true,

    // Disable the `NODE_OPTIONS` env var. Closes `--require /evil.js` injection.
    [FuseV1Options.EnableNodeOptionsEnvironmentVariable]: false,

    // Disable `--inspect`/`--inspect-brk` CLI args. Otherwise the packaged
    // app can be started under a debugger that lets an attacker dump
    // memory and hijack execution.
    [FuseV1Options.EnableNodeCliInspectArguments]: false,

    // Embedded ASAR integrity — Electron hashes the asar at pack time and
    // refuses to load a modified one. Closes GHSA-vmqv-hx8q-j7mg (ASAR
    // integrity bypass) called out in the dep audit.
    [FuseV1Options.EnableEmbeddedAsarIntegrityValidation]: true,

    // Refuse to load any app code outside the signed asar (e.g. a
    // malware-dropped `app/` folder next to the exe).
    [FuseV1Options.OnlyLoadAppFromAsar]: true,

    // Load the V8 snapshot from a fixed, signed location.
    [FuseV1Options.LoadBrowserProcessSpecificV8Snapshot]: false,

    // Grant file access based on current working directory. Leave default
    // (disabled) — our path-jail already restricts fs access.
    [FuseV1Options.GrantFileProtocolExtraPrivileges]: false,
  });

  console.log(`[afterPack] Fuses flipped on ${exePath}`);
};
