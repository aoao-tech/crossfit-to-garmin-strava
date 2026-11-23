# Phase 1 capture guide (Windows 11)

Goal: record the traffic between the Arbox app and its servers inside an Android emulator, so we can see the login request and the "workout for a date" request. Your real phone is only used in step 3, to copy the app. It is never used for capture.

All commands below are PowerShell. Run them from the project folder:

```powershell
cd C:\path\to\garmin-arbox
```

## 1. Install Android Studio

1. Download and install it from https://developer.android.com/studio, keeping the default options. This installs the Android SDK, the emulator and `adb`.
2. Open Android Studio once and finish the setup wizard (Standard setup).
3. Make `adb` available in this PowerShell window:
   ```powershell
   $env:Path += ";$env:LOCALAPPDATA\Android\Sdk\platform-tools"
   ```
   ```powershell
   adb version
   ```
4. If the emulator later complains about hardware acceleration, enable "Windows Hypervisor Platform" in Windows Features and reboot. That's a system setting, so you need to do it yourself.

## 2. Create the emulator (Google APIs image, NOT Google Play)

1. In Android Studio, go to **More Actions > Virtual Device Manager**, then **Create Virtual Device**.
2. Pick **Pixel 7**, then Next.
3. On the system image screen, choose **API 34, x86_64, "Google APIs"**. Use **"Other images"** or the x86 tab if it's not listed. The "Google Play" images are locked, so HTTP Toolkit can't install its certificate there.
4. Finish, but **don't start it yet**.

## 3. Copy the Arbox app from your phone

1. **Turn on USB debugging on the phone:**
   - Go to Settings > About phone > Software information and tap **Build number** 7 times.
   - Go to Settings > Developer options and turn on **USB debugging**.
2. **Connect the phone by USB** and accept the "Allow USB debugging?" prompt on it. Then check that it shows up as `device`:
   ```powershell
   adb devices
   ```
3. **Find the package name** (the `-d` flag means "the USB phone"):
   ```powershell
   adb -d shell pm list packages | Select-String -Pattern arbox
   ```
   It prints something like `package:com.example.arbox`. Use that name below in place of `<PKG>`.
4. **Pull every APK part** (base + splits) into `apks\`, which git ignores:
   ```powershell
   New-Item -ItemType Directory -Force apks | Out-Null
   ```
   ```powershell
   adb -d shell pm path <PKG> | ForEach-Object { adb -d pull ($_ -replace '^package:','') apks\ }
   ```
   ```powershell
   Get-ChildItem apks
   ```
   You should see `base.apk`, and maybe some `split_config.*.apk` files.
5. **Unplug the phone.** It's not needed again.

## 4. Install Arbox in the emulator

1. Start the emulator from the Device Manager (the play button) and wait for the home screen.
2. Install all the parts together (`-e` means "the emulator"):
   ```powershell
   adb -e install-multiple (Get-ChildItem apks\*.apk).FullName
   ```
   It should print `Success`. If it fails with `INSTALL_FAILED_NO_MATCHING_ABIS` or anything else, stop and send me the message.
3. Open Arbox in the emulator once, **without logging in**, just to check that it launches.

## 5. Install HTTP Toolkit and attach it to the emulator

1. Download and install it from https://httptoolkit.com (the free version).
2. With the emulator running and the phone unplugged, open HTTP Toolkit, go to **Intercept**, and click **"Android device via ADB"**.
3. In the emulator, accept the prompts: HTTP Toolkit app install, VPN connection, and certificate. On a Google APIs image it installs a system certificate automatically.
4. Check that it works: open Chrome in the emulator and load any site. It should appear in HTTP Toolkit's **View** tab.

## 6. Capture

In HTTP Toolkit's View tab, clear the list (trash icon) first, then do this in the emulator:

1. Open Arbox and **log in** with your email, then enter the 4-digit code Arbox emails you. This records the "send code" and "verify code" requests.
2. Open **today's** workout (WOD).
3. Go back to **yesterday**, then about **7 days ago**, **14 days ago** and **30 days ago**, if the app lets you. This tells us how much history we can read.
4. Open one day with no class, if there is one. That shows us what "empty" looks like.
5. **Fully close Arbox** (swipe it away from recent apps), then open it again and view today's WOD. This shows how the app stays logged in without a new code (token refresh).
6. Optional but very useful: keep HTTP Toolkit attached, come back the next day, reopen Arbox, and export a second HAR as `arbox-day2.har`. This shows whether the token expires and how it gets renewed.

**If Arbox can't connect or log in while HTTP Toolkit is attached** (a network error, endless spinner, or TLS/certificate errors next to the Arbox requests in HTTP Toolkit), that's probably certificate pinning. **Stop there and tell me.** Don't try workarounds; I'll explain the options first.

## 7. Export

1. In HTTP Toolkit, export the traffic as **HAR** (the export/save button in the View tab).
2. Save it as `C:\path\to\garmin-arbox\captures\raw\arbox.har`. This folder is gitignored and never committed.
3. If HAR export turns out to be locked behind HTTP Toolkit Pro, tell me and I'll switch you to a free capture route.
4. Then tell me "HAR is ready". **Don't paste it in the chat**, since it contains your password and tokens. I'll sanitize it first and only work from the clean copy. Neither the raw nor the clean HAR is ever committed: this repo will be public, and the traffic may include other members' data.
