import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: !!process.env["CI"],
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:5173",
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        launchOptions: {
          args: [
            // Headless Chromium has no output device, so an AudioContext would
            // sit suspended and currentTime would never advance -- which is the
            // one thing these tests need to observe. This gives it a silent
            // device and lets play() start without a user gesture.
            "--autoplay-policy=no-user-gesture-required",
            "--use-fake-device-for-media-stream",
            "--mute-audio",
          ],
        },
      },
    },
  ],
  webServer: {
    command: "npm run dev",
    url: "http://127.0.0.1:5173",
    reuseExistingServer: !process.env["CI"],
    timeout: 60_000,
  },
});
