# Desktop app and Windows installer

The app is a Tauri 2 shell (Rust) around the React interface. It contains no credentials and no
data; it needs only the server address.

## Develop

```bash
cd desktop && npm install
```

```bash
npm run dev
```

opens the interface at http://localhost:1420 in a browser (uses a normal file input instead of the
native picker).

```bash
npm run tauri dev
```

runs the native app (native picker, drag and drop of files from Explorer/Finder).

`VITE_API_URL` in `desktop/.env` sets the default server address baked into a build; each user can
change it on the sign-in screen ("Servidor: …"). It is stored per machine.

## Build the Windows installer

Windows installers are built on Windows. The repository includes
`.github/workflows/desktop-windows.yml`, which:

1. installs Node 22 and stable Rust on `windows-latest`,
2. builds with `VITE_API_URL` from the repository variable `CADASTRO_API_URL`,
3. produces `Cadastro AI_<version>_x64-setup.exe` (NSIS) and `Cadastro AI_<version>_x64_pt-BR.msi`,
4. signs them when `WINDOWS_CERTIFICATE` (base64 .pfx) and `WINDOWS_CERTIFICATE_PASSWORD` secrets
   exist,
5. uploads them as a workflow artifact.

Trigger it manually (Actions → desktop-windows → Run) or by pushing a tag `desktop-vX.Y.Z`.

To build by hand on a Windows PC: install Node 22, Rust (rustup, MSVC toolchain) and the "Desktop
development with C++" build tools, then:

```powershell
cd desktop; npm ci; npx tauri build --bundles nsis,msi
```

Output: `desktop\src-tauri\target\release\bundle\{nsis,msi}\`.

The installer embeds the WebView2 bootstrapper, installs per machine, and needs administrator
rights once. For managed fleets, deploy the `.msi` with Intune/SCCM/GPO.

**State of this repository:** the macOS bundle was built and launched from this machine
(`npx tauri build --bundles app`). The Windows installers have not been produced here because this
machine is a Mac; they come from the workflow above.

## Code signing

Unsigned installers trigger SmartScreen warnings. Use the company's code-signing certificate (OV or
EV). Keep the certificate in the CI secret store, never in the repository.

## Updates

Recommended for an internal tool: publish each signed `.msi` through the existing software
distribution system (Intune/SCCM), which handles staged rollout and rollback. The Tauri updater
plugin is a possible later addition if the company prefers in-app updates; it would need an update
endpoint and a signing key pair and is not enabled in this version.

## Supported platforms

Windows 10/11 x64 is the target. macOS builds work from the same source (`--bundles app,dmg`) and
were used during development.
