// Run UI/body.js, the website's port of BodyTracking/tracking.py, on scripted
// MediaPipe landmarks: no webcam and no MediaPipe. Checks the tracking rules
// and that the webcam is let go when tracking can't start.
const fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const assert = require("node:assert/strict");
const root = process.argv[2];

function load(sandbox = {}) {
  const context = vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(root, "UI/body.js"), "utf8"), context, { filename: "UI/body.js" });
  return context.BuddyBody;
}

// MediaPipe's 33 landmarks; only the ones tracking.py reads are visible.
function pose({ shoulderY = 0.7, noseY = 0.4, face = 0.1, shoulders = 0.3, wristY = 0.9 } = {}) {
  const lms = Array.from({ length: 33 }, () => ({ x: 0.5, y: 0.5, z: 0, visibility: 0.1 }));
  const set = (i, x, y) => { lms[i] = { x, y, z: 0, visibility: 0.9 }; };
  set(0, 0.5, noseY);
  set(7, 0.5 + face / 2, noseY);
  set(8, 0.5 - face / 2, noseY);
  set(11, 0.5 + shoulders / 2, shoulderY);
  set(12, 0.5 - shoulders / 2, shoulderY);
  set(15, 0.7, wristY);
  set(16, 0.3, 0.9);
  return lms;
}

async function main() {
  const { BodyTracker } = load();
  const tracker = new BodyTracker();
  const events = [];
  let t = 0;
  // Hold a pose (null = nobody there) for `seconds` at 15 frames a second.
  const hold = (seconds, lms) => {
    let snap;
    for (let i = 0; i < Math.round(seconds * 15); i++) {
      t += 1 / 15;
      snap = tracker.process(lms, t);
      if (snap.event) events.push(snap.event);
    }
    return snap;
  };

  assert.equal(hold(1, null).state, "away");
  assert.equal(hold(3, pose()).state, "at_desk"); // sits down and holds still long enough to calibrate
  assert.deepEqual(events, ["user_arrived"]);
  assert.equal(hold(0.5, pose({ wristY: 0.3 })).hand_raised, true);
  assert.equal(hold(0.5, pose({ face: 0.15 })).leaning_in, true);
  assert.equal(hold(1.5, pose({ shoulderY: 0.45, noseY: 0.2 })).state, "getting_up");
  assert.equal(hold(1.5, pose()).state, "at_desk");
  const gone = hold(10, null);
  assert.equal(gone.state, "away");
  assert.ok(Math.abs(gone.away_seconds - 9.93) < 0.05, `away_seconds counts from leaving: ${gone.away_seconds}`);
  hold(1, pose());
  assert.deepEqual(events, ["user_arrived", "user_getting_up", "user_sat_back_down", "user_left", "user_returned"]);

  const noop = () => {};
  const insecure = load({ isSecureContext: false, navigator: { mediaDevices: { getUserMedia: noop } } })
    .createCamera({ video: {}, canvas: {}, onSnapshot: noop, onChange: noop });
  assert.equal(insecure.status, "unsupported");
  assert.match(insecure.error, /https/);

  // MediaPipe comes from a CDN, which this sandbox can't import.
  const stopped = [];
  const track = { stop: () => stopped.push(true), addEventListener: noop };
  const stream = { getTracks: () => [track], getVideoTracks: () => [track] };
  const statuses = [];
  const secure = load({ isSecureContext: true, setTimeout, clearTimeout,
    navigator: { mediaDevices: { getUserMedia: async () => stream } } });
  const failing = secure.createCamera({ video: {}, canvas: { getContext: () => null }, onSnapshot: noop,
    onChange: () => statuses.push(failing.status) });
  await failing.start();
  assert.deepEqual(statuses, ["starting", "error"]);
  assert.match(failing.error, /couldn't start/);
  assert.equal(stopped.length, 1, "the webcam is let go when tracking can't start");

  console.log(JSON.stringify({ rules: true, released: true }));
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
