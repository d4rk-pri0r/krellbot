/**
 * Minimal byte-mode QR matrix encoder (ECC level M, versions 1–3).
 * Single-block only — enough for a reconnect token (~22 bytes).
 * No network, no dependency.
 */

type VersionSpec = { version: number; dataCodewords: number; ecCodewords: number };

const VERSIONS: ReadonlyArray<VersionSpec> = [
  { version: 1, dataCodewords: 16, ecCodewords: 10 },
  { version: 2, dataCodewords: 28, ecCodewords: 16 },
  { version: 3, dataCodewords: 44, ecCodewords: 26 },
];

const GALOIS_EXP = new Uint8Array(512);
const GALOIS_LOG = new Uint8Array(256);
(() => {
  let x = 1;
  for (let i = 0; i < 255; i++) {
    GALOIS_EXP[i] = x;
    GALOIS_LOG[x] = i;
    x <<= 1;
    if (x & 0x100) x ^= 0x11d;
  }
  for (let i = 255; i < 512; i++) GALOIS_EXP[i] = GALOIS_EXP[i - 255];
})();

function galoisMul(a: number, b: number): number {
  if (a === 0 || b === 0) return 0;
  return GALOIS_EXP[(GALOIS_LOG[a] + GALOIS_LOG[b]) % 255];
}

function rsGenerator(ecCount: number): number[] {
  let gen = [1];
  for (let i = 0; i < ecCount; i++) {
    const next = new Array<number>(gen.length + 1).fill(0);
    for (let j = 0; j < gen.length; j++) {
      next[j] ^= gen[j];
      next[j + 1] ^= galoisMul(gen[j], GALOIS_EXP[i]);
    }
    gen = next;
  }
  return gen;
}

function rsEncode(data: number[], ecCount: number): number[] {
  const gen = rsGenerator(ecCount);
  const out = new Array<number>(ecCount).fill(0);
  for (const b of data) {
    const factor = b ^ out[0];
    out.shift();
    out.push(0);
    for (let i = 0; i < gen.length - 1; i++) {
      out[i] ^= galoisMul(gen[i + 1], factor);
    }
  }
  return out;
}

function pushBits(bits: number[], val: number, len: number): void {
  for (let i = len - 1; i >= 0; i--) bits.push((val >>> i) & 1);
}

function bitsToBytes(bits: number[]): number[] {
  const bytes: number[] = [];
  for (let i = 0; i < bits.length; i += 8) {
    let v = 0;
    for (let j = 0; j < 8; j++) v = (v << 1) | (bits[i + j] ?? 0);
    bytes.push(v);
  }
  return bytes;
}

function chooseVersion(byteLen: number): VersionSpec {
  for (const spec of VERSIONS) {
    // mode(4) + count(8) + data + terminator(4)
    const needed = Math.ceil((4 + 8 + byteLen * 8 + 4) / 8);
    if (needed <= spec.dataCodewords) return spec;
  }
  throw new Error("qr payload too long for versions 1–3");
}

function setModule(
  modules: boolean[][],
  reserved: boolean[][],
  row: number,
  col: number,
  dark: boolean,
): void {
  modules[row][col] = dark;
  reserved[row][col] = true;
}

function drawFinder(modules: boolean[][], reserved: boolean[][], row: number, col: number): void {
  for (let r = -1; r <= 7; r++) {
    for (let c = -1; c <= 7; c++) {
      const rr = row + r;
      const cc = col + c;
      if (rr < 0 || cc < 0 || rr >= modules.length || cc >= modules.length) continue;
      const onPattern =
        (r >= 0 && r <= 6 && (c === 0 || c === 6)) ||
        (c >= 0 && c <= 6 && (r === 0 || r === 6)) ||
        (r >= 2 && r <= 4 && c >= 2 && c <= 4);
      // Quiet-zone separators around finders stay light and reserved.
      const dark = r >= 0 && r <= 6 && c >= 0 && c <= 6 ? onPattern : false;
      setModule(modules, reserved, rr, cc, dark);
    }
  }
}

function drawTiming(modules: boolean[][], reserved: boolean[][]): void {
  for (let i = 8; i < modules.length - 8; i++) {
    if (!reserved[6][i]) setModule(modules, reserved, 6, i, i % 2 === 0);
    if (!reserved[i][6]) setModule(modules, reserved, i, 6, i % 2 === 0);
  }
}

function drawAlignment(modules: boolean[][], reserved: boolean[][], version: number): void {
  if (version < 2) return;
  const pos = 4 * version + 10; // 18, 22 for v2/v3
  for (let r = -2; r <= 2; r++) {
    for (let c = -2; c <= 2; c++) {
      if (reserved[pos + r]?.[pos + c]) continue;
      const dark = Math.max(Math.abs(r), Math.abs(c)) !== 1;
      setModule(modules, reserved, pos + r, pos + c, dark);
    }
  }
}

function formatBits(mask: number): number {
  let data = (0b00 << 3) | mask; // ECC M
  let d = data << 10;
  const poly = 0b10100110111;
  while (31 - Math.clz32(d) >= 10) {
    d ^= poly << (31 - Math.clz32(d) - 10);
  }
  return ((data << 10) | d) ^ 0b101010000010010;
}

function reserveFormat(reserved: boolean[][]): void {
  const size = reserved.length;
  for (let i = 0; i <= 8; i++) {
    reserved[8][i] = true;
    reserved[i][8] = true;
  }
  for (let i = 0; i <= 7; i++) {
    reserved[8][size - 1 - i] = true;
    reserved[size - 1 - i][8] = true;
  }
  reserved[size - 8][8] = true;
}

function drawFormat(modules: boolean[][], mask: number): void {
  const bits = formatBits(mask);
  const size = modules.length;
  const positions: Array<[number, number]> = [];
  for (let i = 0; i <= 5; i++) positions.push([8, i]);
  positions.push([8, 7], [8, 8], [7, 8]);
  for (let i = 9; i <= 14; i++) positions.push([14 - i, 8]);
  for (let i = 0; i < 15; i++) {
    const [r, c] = positions[i];
    modules[r][c] = ((bits >> i) & 1) === 1;
  }
  for (let i = 0; i <= 7; i++) modules[8][size - 1 - i] = ((bits >> i) & 1) === 1;
  for (let i = 8; i <= 14; i++) modules[size - 15 + i][8] = ((bits >> i) & 1) === 1;
  modules[size - 8][8] = true;
}

function maskFn(mask: number, row: number, col: number): boolean {
  switch (mask) {
    case 0:
      return (row + col) % 2 === 0;
    case 1:
      return row % 2 === 0;
    case 2:
      return col % 3 === 0;
    case 3:
      return (row + col) % 3 === 0;
    case 4:
      return (Math.floor(row / 2) + Math.floor(col / 3)) % 2 === 0;
    case 5:
      return ((row * col) % 2) + ((row * col) % 3) === 0;
    case 6:
      return (((row * col) % 2) + ((row * col) % 3)) % 2 === 0;
    default:
      return (((row + col) % 2) + ((row * col) % 3)) % 2 === 0;
  }
}

function placeData(modules: boolean[][], reserved: boolean[][], dataBits: number[]): void {
  const size = modules.length;
  let bitIndex = 0;
  let upward = true;
  for (let col = size - 1; col > 0; col -= 2) {
    if (col === 6) col -= 1;
    for (let i = 0; i < size; i++) {
      const row = upward ? size - 1 - i : i;
      for (let c = 0; c < 2; c++) {
        const cc = col - c;
        if (reserved[row][cc]) continue;
        modules[row][cc] = (dataBits[bitIndex] ?? 0) === 1;
        bitIndex += 1;
      }
    }
    upward = !upward;
  }
}

function penalty(modules: boolean[][]): number {
  const size = modules.length;
  let score = 0;
  for (let r = 0; r < size; r++) {
    let run = 1;
    for (let c = 1; c < size; c++) {
      if (modules[r][c] === modules[r][c - 1]) {
        run += 1;
        if (run === 5) score += 3;
        else if (run > 5) score += 1;
      } else run = 1;
    }
  }
  for (let c = 0; c < size; c++) {
    let run = 1;
    for (let r = 1; r < size; r++) {
      if (modules[r][c] === modules[r - 1][c]) {
        run += 1;
        if (run === 5) score += 3;
        else if (run > 5) score += 1;
      } else run = 1;
    }
  }
  let dark = 0;
  for (const row of modules) for (const cell of row) if (cell) dark += 1;
  score += Math.floor(Math.abs((dark * 100) / (size * size) - 50) / 5) * 10;
  return score;
}

/** Encode `text` as a QR module matrix (`true` = dark module). */
export function encodeQrMatrix(text: string): boolean[][] {
  const raw = Array.from(new TextEncoder().encode(text));
  const spec = chooseVersion(raw.length);
  const bits: number[] = [];
  pushBits(bits, 0b0100, 4);
  pushBits(bits, raw.length, 8);
  for (const b of raw) pushBits(bits, b, 8);
  const capacity = spec.dataCodewords * 8;
  pushBits(bits, 0, Math.min(4, capacity - bits.length));
  while (bits.length % 8 !== 0) pushBits(bits, 0, 1);
  const dataBytes = bitsToBytes(bits);
  const pads = [0xec, 0x11];
  let p = 0;
  while (dataBytes.length < spec.dataCodewords) {
    dataBytes.push(pads[p % 2]);
    p += 1;
  }
  const ec = rsEncode(dataBytes, spec.ecCodewords);
  const codewords = dataBytes.concat(ec);
  const dataBits: number[] = [];
  for (const cw of codewords) pushBits(dataBits, cw, 8);

  const size = spec.version * 4 + 17;
  let best: boolean[][] | null = null;
  let bestScore = Infinity;

  for (let mask = 0; mask < 8; mask++) {
    const modules = Array.from({ length: size }, () => Array<boolean>(size).fill(false));
    const reserved = Array.from({ length: size }, () => Array<boolean>(size).fill(false));
    drawFinder(modules, reserved, 0, 0);
    drawFinder(modules, reserved, 0, size - 7);
    drawFinder(modules, reserved, size - 7, 0);
    drawAlignment(modules, reserved, spec.version);
    drawTiming(modules, reserved);
    reserveFormat(reserved);
    placeData(modules, reserved, dataBits);
    for (let r = 0; r < size; r++) {
      for (let c = 0; c < size; c++) {
        if (!reserved[r][c] && maskFn(mask, r, c)) modules[r][c] = !modules[r][c];
      }
    }
    drawFormat(modules, mask);
    const score = penalty(modules);
    if (score < bestScore) {
      bestScore = score;
      best = modules.map((row) => row.slice());
    }
  }
  if (!best) throw new Error("qr encode failed");
  return best;
}
