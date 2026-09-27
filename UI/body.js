// Webcam body tracking in the website, for when the app server has no camera
// of its own (on Vercel, or without OpenCV/MediaPipe installed; companion.py's
// CameraWorker is the server-side version).
//
// A port of BodyTracking/tracking.py: MediaPipe Pose finds you in the webcam
// picture, and the same rules and numbers turn that into at_desk / getting_up
// / away, one-frame events, a raised hand and leaning in. The video never
// leaves the browser; app.js sends only those signals to POST /api/body.
//
// Not ported: tracking.py's CameraMotionDetector, which needs OpenCV. Moving
// the webcam can look like getting up until you're back where you sat.
//
//   BuddyBody.BodyTracker   the rules alone: process(landmarks, seconds) -> snapshot
//   BuddyBody.supported()   whether this page may use a webcam (HTTPS or localhost)
//   BuddyBody.createCamera  webcam + MediaPipe + BodyTracker, drawing the skeleton

(() => {
  // MediaPipe's web build, and the model tracking.py downloads.
  const VISION = "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@1.0.1";
  const MODEL_URL = "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    + "pose_landmarker_lite/float16/latest/pose_landmarker_lite.task";
  // About 15 frames a second. Browsers slow this to about once a second in hidden tabs.
  const FRAME_MS = 66;

  // Same values as BodyTracking/tracking.py; the reasons are there.
  const MIN_VISIBILITY = 0.5;
  const AWAY_AFTER_SECONDS = 3.0;
  const RETURN_AFTER_SECONDS = 0.7;
  const FAR_AWAY_RATIO = 0.5;
  const GETTING_UP_AFTER_SECONDS = 0.8;
  const SAT_BACK_AFTER_SECONDS = 1.0;
  const STAND_RISE = 0.20;
  const SIT_RISE = 0.10;
  const CALIBRATION_SECONDS = 2.0;
  const CALIBRATION_MAX_WOBBLE = 0.10;
  const LEAN_IN_RATIO = 1.3;

  // Indices into MediaPipe's 33 pose landmarks.
  const LM = {
    NOSE: 0, LEFT_EAR: 7, RIGHT_EAR: 8, LEFT_SHOULDER: 11, RIGHT_SHOULDER: 12, LEFT_WRIST: 15, RIGHT_WRIST: 16,
  };

  // Skeleton lines to draw, as [start, end] landmark index pairs.
  const CONNECTIONS = [
    // face
    [0, 1], [1, 2], [2, 3], [3, 7], [0, 4], [4, 5], [5, 6], [6, 8], [9, 10],
    // torso
    [11, 12], [11, 23], [12, 24], [23, 24],
    // arms and hands
    [11, 13], [13, 15], [15, 17], [15, 19], [15, 21], [17, 19],
    [12, 14], [14, 16], [16, 18], [16, 20], [16, 22], [18, 20],
    // legs and feet
    [23, 25], [25, 27], [27, 29], [27, 31], [29, 31],
    [24, 26], [26, 28], [28, 30], [28, 32], [30, 32],
  ];

  const seen = (lms, i) => lms[i].visibility >= MIN_VISIBILITY;
  const bodySeen = (lms) => Boolean(lms) && [LM.NOSE, LM.LEFT_SHOULDER, LM.RIGHT_SHOULDER].some((i) => seen(lms, i));

  // tracking.py's BodySnapshot: the fields POST /api/body takes, then raw
  // measurements (0 = not visible) used for calibration.
  function readPose(lms) {
    const snap = {
      state: "away", present: false, event: null, away_seconds: 0, hand_raised: false, leaning_in: false,
      closeness: 0, faceSize: 0, shoulderY: 0, noseY: 0,
    };
    if (!lms) return snap;
    // y grows downward, so "above" means a smaller y.
    const raised = (wrist, shoulder) => seen(lms, wrist) && seen(lms, shoulder) && lms[wrist].y < lms[shoulder].y;
    snap.hand_raised = raised(LM.LEFT_WRIST, LM.LEFT_SHOULDER) || raised(LM.RIGHT_WRIST, LM.RIGHT_SHOULDER);
    // Shoulder width as a fraction of frame width. Bigger = closer to camera.
    if (seen(lms, LM.LEFT_SHOULDER) && seen(lms, LM.RIGHT_SHOULDER)) {
      snap.closeness = Math.abs(lms[LM.LEFT_SHOULDER].x - lms[LM.RIGHT_SHOULDER].x);
    }
    // Ear-to-ear width; stays in frame when the user is very close.
    if (seen(lms, LM.LEFT_EAR) && seen(lms, LM.RIGHT_EAR)) {
      snap.faceSize = Math.abs(lms[LM.LEFT_EAR].x - lms[LM.RIGHT_EAR].x);
    }
    const shoulders = [LM.LEFT_SHOULDER, LM.RIGHT_SHOULDER].filter((i) => seen(lms, i)).map((i) => lms[i].y);
    if (shoulders.length) snap.shoulderY = shoulders.reduce((a, b) => a + b) / shoulders.length;
    if (seen(lms, LM.NOSE) && lms[LM.NOSE].y > 0) snap.noseY = lms[LM.NOSE].y;
    return snap;
  }

  // Turns noisy per-frame detections into stable present / away state.
  class PresenceTracker {
    constructor() {
      this.present = false;
      this.seenSince = null;
      this.unseenSince = null;
      this.awaySince = null;
      this.everPresent = false;
    }

    update(isSeen, now, snap) {
      if (isSeen) {
        this.unseenSince = null;
        this.seenSince ??= now;
        if (!this.present && now - this.seenSince >= RETURN_AFTER_SECONDS) {
          this.present = true;
          snap.event = this.everPresent ? "user_returned" : "user_arrived";
          this.everPresent = true;
          this.awaySince = null;
        }
      } else {
        this.seenSince = null;
        this.unseenSince ??= now;
        if (this.present && now - this.unseenSince >= AWAY_AFTER_SECONDS) {
          this.present = false;
          snap.event = "user_left";
          this.awaySince = this.unseenSince;
        }
      }
      snap.present = this.present;
      if (!this.present && this.awaySince !== null) snap.away_seconds = now - this.awaySince;
    }
  }

  // Debounces per-frame "looks like they're getting up" into getting_up state.
  class GettingUpDetector {
    constructor() {
      this.reset();
    }

    reset() {
      this.gettingUp = false;
      this.since = null; // when the getting-up signal started
      this.settledSince = null;
    }

    update(signal, now, snap) {
      if (signal === null) return; // can't tell this frame; keep current state and timers
      if (signal) {
        this.settledSince = null;
        this.since ??= now;
        if (!this.gettingUp && snap.event === null && now - this.since >= GETTING_UP_AFTER_SECONDS) {
          this.gettingUp = true;
          snap.event = "user_getting_up";
        }
      } else {
        this.since = null;
        this.settledSince ??= now;
        if (this.gettingUp && snap.event === null && now - this.settledSince >= SAT_BACK_AFTER_SECONDS) {
          this.gettingUp = false;
          snap.event = "user_sat_back_down";
        }
      }
    }
  }

  // Learns how the user normally sits from the first steady CALIBRATION_SECONDS stretch.
  class SeatedBaseline {
    constructor() {
      this.reset();
    }

    reset() {
      this.ready = false;
      this.closeness = this.faceSize = this.shoulderY = this.noseY = 0;
      this.samples = []; // [time, closeness, faceSize, shoulderY, noseY]
    }

    update(snap, now) {
      if (this.ready) return;
      // Only learn from a normal upright pose: facing the camera, nose well above shoulders.
      if (!snap.noseY || !snap.shoulderY || snap.faceSize < 0.05) return;
      if (snap.shoulderY - snap.noseY < 0.15) return;
      this.samples.push([now, snap.closeness, snap.faceSize, snap.shoulderY, snap.noseY]);
      while (now - this.samples[0][0] > CALIBRATION_SECONDS) this.samples.shift();
      if (now - this.samples[0][0] < CALIBRATION_SECONDS * 0.9 || this.samples.length < 10) return;

      const column = (i) => this.samples.map((s) => s[i]).filter((v) => v > 0).sort((a, b) => a - b);
      // 10th-90th percentile range, so a few glitchy frames don't count.
      const spread = (i) => {
        const vals = column(i);
        return vals[Math.floor(vals.length * 9 / 10)] - vals[Math.floor(vals.length / 10)];
      };
      if (spread(3) > CALIBRATION_MAX_WOBBLE || spread(4) > CALIBRATION_MAX_WOBBLE) return; // not steady yet
      const median = (i) => {
        const vals = column(i);
        return vals.length ? vals[Math.floor(vals.length / 2)] : 0;
      };
      [this.closeness, this.faceSize, this.shoulderY, this.noseY] = [1, 2, 3, 4].map(median);
      this.ready = true;
    }
  }

  // tracking.py's BodyTracker without the camera: landmarks in, snapshot out.
  class BodyTracker {
    constructor() {
      this.presence = new PresenceTracker();
      this.seated = new SeatedBaseline();
      this.gettingUp = new GettingUpDetector();
    }

    // lms: one pose's landmarks from the raw (unmirrored) camera frame, or
    // null when nobody's there. now: seconds.
    process(lms, now) {
      const snap = readPose(lms);
      this.presence.update(this.atDesk(lms, snap), now, snap);
      if (snap.event === "user_arrived" || snap.event === "user_returned") {
        this.seated.reset(); // they may sit differently this time
      }
      if (!snap.present) {
        this.gettingUp.reset();
        snap.state = "away";
        return snap;
      }
      if (!this.seated.ready) this.seated.update(snap, now); // still learning how they normally sit
      else this.gettingUp.update(this.looksLikeGettingUp(lms, snap), now, snap);
      snap.state = this.gettingUp.gettingUp ? "getting_up" : "at_desk";
      if (this.seated.ready && snap.state === "at_desk") {
        snap.leaning_in = snap.faceSize > this.seated.faceSize * LEAN_IN_RATIO;
      }
      return snap;
    }

    // true = standing up, false = seated normally, null = can't tell (keep
    // current state). Only a clear rise of the shoulders counts.
    looksLikeGettingUp(lms, snap) {
      if (!bodySeen(lms) || !snap.shoulderY) return null;
      const rise = this.seated.shoulderY - snap.shoulderY; // positive = higher than seated
      if (rise >= STAND_RISE) return true;
      if (rise <= SIT_RISE) return false;
      return null; // in between: keep current state so it doesn't flicker
    }

    atDesk(lms, snap) {
      if (!bodySeen(lms)) return false;
      const normal = this.seated.ready ? this.seated.closeness : 0;
      // closeness is 0 when a shoulder is out of frame (e.g. very close), so
      // only a small but nonzero width means "far away".
      return !(normal && snap.closeness > 0 && snap.closeness < normal * FAR_AWAY_RATIO);
    }
  }

  // What POST /api/body takes.
  const signals = (snap) => ({
    state: snap.state, present: snap.present, event: snap.event,
    away_seconds: Math.round(snap.away_seconds * 10) / 10, hand_raised: snap.hand_raised, leaning_in: snap.leaning_in,
  });

  // --- Webcam + MediaPipe ------------------------------------------------------

  const supported = () => Boolean(globalThis.isSecureContext && globalThis.navigator?.mediaDevices?.getUserMedia);

  let loading = null; // one model per page, loaded on the first start
  function loadLandmarker() {
    if (!loading) {
      loading = (async () => {
        const { FilesetResolver, PoseLandmarker } = await import(`${VISION}/vision_bundle.mjs`);
        const files = await FilesetResolver.forVisionTasks(`${VISION}/wasm`);
        const create = (delegate) => PoseLandmarker.createFromOptions(files, {
          baseOptions: { modelAssetPath: MODEL_URL, delegate }, runningMode: "VIDEO", numPoses: 1,
        });
        try {
          return await create("GPU");
        } catch {
          return await create("CPU"); // no WebGL
        }
      })();
      loading.catch(() => { loading = null; }); // try again on the next start
    }
    return loading;
  }

  function startError(err) {
    switch (err?.name) {
      case "NotAllowedError":
      case "SecurityError":
        return "Camera access is blocked. Allow the camera for this site (the icon in the address bar), then try again.";
      case "NotFoundError":
      case "OverconstrainedError":
        return "No webcam found.";
      case "NotReadableError":
        return "The webcam is in use by another app. Close it there, then try again.";
      default:
        return `Body tracking couldn't start: ${err?.message || err}`;
    }
  }

  // Like tracking.py's draw_skeleton: white bones, amber joints. The canvas
  // matches the video's size and is mirrored with it in CSS.
  function drawSkeleton(canvas, video, lms) {
    const w = video.videoWidth, h = video.videoHeight;
    if (canvas.width !== w || canvas.height !== h) Object.assign(canvas, { width: w, height: h });
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, w, h);
    if (!lms) return;
    const unit = Math.max(2, Math.round(w / 240));
    ctx.strokeStyle = "#fff";
    ctx.lineWidth = unit;
    ctx.beginPath();
    for (const [a, b] of CONNECTIONS) {
      if (seen(lms, a) && seen(lms, b)) {
        ctx.moveTo(lms[a].x * w, lms[a].y * h);
        ctx.lineTo(lms[b].x * w, lms[b].y * h);
      }
    }
    ctx.stroke();
    ctx.fillStyle = "rgb(255, 200, 0)";
    lms.forEach((p, i) => {
      if (seen(lms, i)) ctx.fillRect(p.x * w - unit * 2, p.y * h - unit * 2, unit * 4, unit * 4);
    });
  }

  // The page's webcam, tracked. onSnapshot gets each frame's signals;
  // onChange runs whenever status changes.
  //   status: "off" | "starting" | "on" | "error" | "unsupported"
  function createCamera({ video, canvas, onSnapshot, onChange }) {
    const ok = supported();
    const cam = {
      status: ok ? "off" : "unsupported",
      error: ok ? "" : "The camera only works on a secure page. Open this site with https:// (or at http://127.0.0.1:8765).",
      snapshot: null, // the latest signals while on
      start,
      stop,
    };
    let stream = null, timer = null, run = 0;

    function set(status, error = "") {
      cam.status = status;
      cam.error = error;
      onChange();
    }

    function release() {
      clearTimeout(timer);
      stream?.getTracks().forEach((track) => track.stop());
      stream = null;
      video.srcObject = null;
      canvas.getContext("2d")?.clearRect(0, 0, canvas.width, canvas.height);
      cam.snapshot = null;
    }

    async function start() {
      if (cam.status !== "off" && cam.status !== "error") return;
      const id = ++run;
      set("starting");
      const model = loadLandmarker();
      model.catch(() => {}); // reported below, after the camera permission prompt
      let media = null;
      try {
        media = await navigator.mediaDevices.getUserMedia({
          audio: false, video: { width: { ideal: 640 }, height: { ideal: 480 } },
        });
        const landmarker = await model;
        if (id !== run) { // stopped while starting
          media.getTracks().forEach((track) => track.stop());
          return;
        }
        stream = media;
        stream.getVideoTracks()[0]?.addEventListener("ended", () => {
          if (id !== run) return;
          release();
          set("error", "Lost the camera feed.");
        });
        video.srcObject = stream;
        await video.play();
        if (id !== run) return;
        const tracker = new BodyTracker();
        set("on");
        const step = () => {
          if (id !== run) return;
          try {
            if (video.readyState >= 2) { // HAVE_CURRENT_DATA
              const now = performance.now();
              const lms = landmarker.detectForVideo(video, now).landmarks[0] ?? null;
              cam.snapshot = signals(tracker.process(lms, now / 1000));
              drawSkeleton(canvas, video, lms);
              onSnapshot(cam.snapshot);
            }
          } catch (err) {
            release();
            set("error", `Body tracking stopped: ${err?.message || err}`);
            return;
          }
          timer = setTimeout(step, FRAME_MS);
        };
        step();
      } catch (err) {
        media?.getTracks().forEach((track) => track.stop());
        if (id !== run) return;
        release();
        set("error", startError(err));
      }
    }

    function stop() {
      if (cam.status === "unsupported") return;
      run++;
      release();
      set("off");
    }

    return cam;
  }

  globalThis.BuddyBody = { BodyTracker, supported, createCamera };
})();
