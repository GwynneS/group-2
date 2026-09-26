const canvas = document.querySelector("#buddy-sprite");
const caption = document.querySelector("#animation-caption");
const context = canvas.getContext("2d");

const colors = {
    outline: "#171529",
    black: "#202036",
    hairShine: "#57536f",
    white: "#fff4df",
    earShade: "#d5bedf",
    skin: "#f3c5aa",
    skinLight: "#ffdfcb",
    skinShade: "#d99c91",
    blush: "#dc8296",
    blue: "#3978d8",
    lightBlue: "#79c8ed",
    darkBlue: "#244a91",
    blueShine: "#a4e4f5",
    blueShadow: "#315ab0",
    yellow: "#ffe181",
    red: "#f05c72",
    tear: "#7ed7ff",
    bed: "#b68ae0",
};

const validStates = new Set([
    "lounging",
    "happy",
    "sad",
    "tired",
    "angry",
    "hungry",
    "encouragement",
]);

const labels = {
    lounging: "Lounging",
    happy: "Happy",
    sad: "Sad",
    tired: "Tired",
    angry: "Angry",
    hungry: "Hungry",
    encouragement: "You got this!",
};

let animation = "lounging";
let message = labels.lounging;
let lastDrawnFrame = -1;
let lastDrawnAnimation = "";

function pixel(x, y, color) {
    context.fillStyle = color;
    context.fillRect(x * 2, y * 2, 2, 2);
}

function block(x, y, width, height, color) {
    context.fillStyle = color;
    context.fillRect(x * 2, y * 2, width * 2, height * 2);
}

function finePixel(x, y, color) {
    context.fillStyle = color;
    context.fillRect(x, y, 1, 1);
}

function fineBlock(x, y, width, height, color) {
    context.fillStyle = color;
    context.fillRect(x, y, width, height);
}

function drawHead(x, y, expression, blink) {
    block(x + 3, y, 4, 6, colors.black);
    block(x + 4, y + 2, 2, 3, colors.white);
    block(x + 13, y, 4, 6, colors.black);
    block(x + 14, y + 2, 2, 3, colors.white);

    block(x + 2, y + 5, 16, 3, colors.black);
    block(x + 1, y + 7, 3, 8, colors.black);
    block(x + 16, y + 7, 3, 8, colors.black);
    block(x + 3, y + 7, 14, 10, colors.skin);
    block(x + 7, y + 5, 3, 5, colors.white);
    block(x + 10, y + 6, 3, 3, colors.black);
    block(x + 13, y + 5, 3, 4, colors.white);

    if (expression === "angry") {
        pixel(x + 5, y + 9, colors.red);
        pixel(x + 13, y + 9, colors.red);
        block(x + 5, y + 10, 2, 1, colors.outline);
        block(x + 12, y + 10, 2, 1, colors.outline);
    } else if (expression === "tired" || blink) {
        block(x + 5, y + 11, 2, 1, colors.outline);
        block(x + 12, y + 11, 2, 1, colors.outline);
    } else {
        pixel(x + 5, y + 10, colors.white);
        block(x + 6, y + 10, 2, 2, colors.outline);
        pixel(x + 7, y + 10, colors.white);
        pixel(x + 12, y + 10, colors.white);
        block(x + 13, y + 10, 2, 2, colors.outline);
        pixel(x + 14, y + 10, colors.white);
    }

    pixel(x + 4, y + 13, colors.blush);
    pixel(x + 15, y + 13, colors.blush);
    if (expression === "happy" || expression === "encouragement") {
        block(x + 9, y + 13, 2, 1, colors.red);
    } else if (expression === "sad") {
        block(x + 9, y + 13, 2, 1, colors.darkBlue);
    } else if (expression === "angry") {
        block(x + 9, y + 12, 2, 2, colors.red);
    } else {
        pixel(x + 9, y + 13, colors.outline);
    }
}

function drawLounging(frame) {
    block(3, 27, 27, 2, colors.bed);
    block(5, 25, 23, 2, colors.lightBlue);
    block(25, 19, 3, 2, colors.blue);
    block(27, 17 + frame, 2, 2, colors.blue);
    block(15, 19, 12, 6, colors.blue);
    block(15, 24, 8, 2, colors.darkBlue);
    block(22, 24, 4, 2, colors.skin);
    block(7, 21, 11, 5, colors.blue);
    drawHead(3, 7 - frame, "tired", frame === 1);
}

function drawStanding(state, frame) {
    const bob = (state === "happy" || state === "encouragement") && frame ? 1 : 0;
    const headY = 2 - bob;

    block(8, 18, 16, 9, colors.blue);
    block(8, 18, 16, 2, colors.lightBlue);

    if (state === "happy") {
        block(3, 17, 4, 5, colors.blue);
        block(4, 14, 2, 4, colors.skin);
        block(25, 17, 4, 5, colors.blue);
        block(26, 14, 2, 4, colors.skin);
    } else if (state === "encouragement") {
        block(4, 18, 4, 6, colors.blue);
        block(25, 14, 4, 5, colors.blue);
        block(26, 11, 2, 4, colors.skin);
        block(27, 9, 2, 2, colors.yellow);
        pixel(26, 8, colors.yellow);
        pixel(29, 10, colors.yellow);
    } else {
        block(4, 19, 5, 6, colors.blue);
        block(23, 19, 5, 6, colors.blue);
        if (state === "hungry") {
            block(11, 22, 10, 2, colors.skin);
            block(12, 21, 2, 2, colors.skin);
            block(18, 21, 2, 2, colors.skin);
            block(23, 9, 4, 3, colors.white);
            pixel(26, 12, colors.white);
            block(24, 10, 2, 1, colors.yellow);
            pixel(25, 9, colors.yellow);
        } else if (state === "angry") {
            block(7, 21, 18, 3, colors.lightBlue);
            block(8, 20, 4, 2, colors.blue);
            block(20, 20, 4, 2, colors.blue);
            block(25, 5, 2, 4, colors.red);
            pixel(25, 10, colors.red);
        } else if (state === "sad") {
            block(24, 14, 1, 3, colors.tear);
            pixel(24, 18, colors.tear);
        } else if (state === "tired") {
            pixel(25, 7, colors.lightBlue);
            block(26, 6, 2, 1, colors.lightBlue);
            pixel(27, 5, colors.lightBlue);
        }
    }

    block(15, 20, 2, 6, colors.darkBlue);
    block(10, 26, 5, 4, colors.darkBlue);
    block(18, 26, 5, 4, colors.darkBlue);
    block(9, 30, 6, 2, colors.outline);
    block(18, 30, 6, 2, colors.outline);
    drawHead(6, headY, state, state === "happy" && frame === 1);
}

function drawBuddy(nextAnimation, frame) {
    context.clearRect(0, 0, canvas.width, canvas.height);
    if (nextAnimation === "lounging") {
        drawLounging(frame);
    } else {
        drawStanding(nextAnimation, frame);
    }
    drawFineDetails(nextAnimation, frame);
}

function drawFineDetails(state, frame) {
    const lounging = state === "lounging";
    const headX = lounging ? 3 : 6;
    const headY = lounging ? 7 - frame : 2 - ((state === "happy" || state === "encouragement") && frame ? 1 : 0);

    finePixel((headX + 4) * 2 + 1, (headY + 2) * 2, colors.earShade);
    finePixel((headX + 5) * 2, (headY + 3) * 2 + 1, colors.white);
    finePixel((headX + 14) * 2 + 1, (headY + 2) * 2, colors.earShade);
    finePixel((headX + 15) * 2, (headY + 3) * 2 + 1, colors.white);

    finePixel((headX + 8) * 2, (headY + 6) * 2, colors.hairShine);
    finePixel((headX + 9) * 2 + 1, (headY + 7) * 2, colors.white);
    finePixel((headX + 2) * 2, (headY + 9) * 2, colors.hairShine);
    finePixel((headX + 16) * 2 + 1, (headY + 10) * 2, colors.hairShine);
    finePixel((headX + 4) * 2, (headY + 8) * 2, colors.skinLight);
    finePixel((headX + 15) * 2, (headY + 8) * 2 + 1, colors.skinLight);
    finePixel((headX + 9) * 2, (headY + 12) * 2, colors.skinShade);
    finePixel((headX + 10) * 2 + 1, (headY + 12) * 2, colors.white);

    if (lounging) {
        fineBlock(31, 40, 18, 1, colors.blueShine);
        fineBlock(31, 48, 12, 1, colors.blueShadow);
        finePixel(36, 44, colors.blueShine);
        finePixel(43, 46, colors.lightBlue);
        finePixel(53, 38 + frame * 2, colors.blueShine);
        finePixel(55, 36 + frame * 2, colors.blueShadow);
    } else {
        fineBlock(18, 38, 28, 1, colors.blueShine);
        fineBlock(31, 41, 1, 13, colors.darkBlue);
        fineBlock(32, 41, 1, 12, colors.blueShine);
        fineBlock(22, 42, 1, 8, colors.blueShadow);
        fineBlock(42, 42, 1, 8, colors.blueShadow);
        finePixel(29, 42, colors.white);
        finePixel(35, 42, colors.white);
        fineBlock(27, 48, 2, 1, colors.blueShine);
        fineBlock(35, 48, 2, 1, colors.blueShine);
        finePixel(21, 50, colors.lightBlue);
        finePixel(43, 50, colors.lightBlue);
        fineBlock(22, 61, 5, 1, colors.darkBlue);
        fineBlock(38, 61, 5, 1, colors.darkBlue);
    }

    if (state === "happy") {
        finePixel(4, 21, colors.yellow);
        finePixel(7, 18, colors.yellow);
        finePixel(56, 20, colors.yellow);
        finePixel(59, 17, colors.yellow);
    } else if (state === "sad") {
        fineBlock(45, 29, 2, 5, colors.tear);
        finePixel(46, 35, colors.white);
    } else if (state === "tired") {
        finePixel(54, 10, colors.lightBlue);
        fineBlock(55, 8, 3, 1, colors.lightBlue);
        finePixel(59, 7, colors.lightBlue);
    } else if (state === "angry") {
        finePixel(53, 9, colors.red);
        finePixel(56, 7, colors.red);
        fineBlock(55, 11, 2, 2, colors.red);
    } else if (state === "hungry") {
        fineBlock(49, 18, 4, 2, colors.yellow);
        finePixel(51, 17, colors.white);
        finePixel(52, 20, colors.red);
    } else if (state === "encouragement") {
        finePixel(57, 15, colors.yellow);
        fineBlock(56, 16, 3, 1, colors.yellow);
        finePixel(57, 17, colors.yellow);
        finePixel(7, 13, colors.white);
        finePixel(9, 11, colors.yellow);
    } else if (frame) {
        finePixel(5, 16, colors.white);
        finePixel(57, 23, colors.blueShine);
    }
}

async function readPythonState() {
    try {
        const response = await fetch("/api/state", { cache: "no-store" });
        if (!response.ok) return;

        const data = await response.json();
        if (validStates.has(data.animation)) {
            animation = data.animation;
            message = data.message || labels[animation];
            caption.textContent = message;
            canvas.setAttribute(
                "aria-label",
                `Pixel cat companion, ${labels[animation].toLowerCase()}`,
            );
        }
    } catch {
        caption.textContent = "Waiting for Python companion...";
    }
}

function animate(now) {
    const frame = Math.floor(now / 320) % 2;
    if (frame !== lastDrawnFrame || animation !== lastDrawnAnimation) {
        drawBuddy(animation, frame);
        lastDrawnFrame = frame;
        lastDrawnAnimation = animation;
    }
    window.requestAnimationFrame(animate);
}

readPythonState();
window.setInterval(readPythonState, 300);
window.requestAnimationFrame(animate);