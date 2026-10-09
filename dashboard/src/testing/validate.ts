// Runtime structural check of hub messages against docs/WS_SCHEMA.md (v1). Used by tests to keep
// the mock (and later the real hub's output) honest. Returns a list of problems; empty = valid.

type Obj = Record<string, unknown>;

const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);
const isInt = (v: unknown) => typeof v === "number" && Number.isInteger(v);
const isNum = (v: unknown) => typeof v === "number" && Number.isFinite(v);
const isStr = (v: unknown) => typeof v === "string";
const isBool = (v: unknown) => typeof v === "boolean";
const orNull = (check: (v: unknown) => boolean) => (v: unknown) => v === null || check(v);

class Checker {
  readonly errors: string[] = [];

  field(obj: Obj, key: string, check: (v: unknown) => boolean, path: string): void {
    if (!(key in obj)) this.errors.push(`${path}.${key}: missing`);
    else if (!check(obj[key])) this.errors.push(`${path}.${key}: bad value ${JSON.stringify(obj[key])}`);
  }

  object(v: unknown, path: string, fn: (o: Obj) => void): void {
    if (!isObj(v)) {
      this.errors.push(`${path}: not an object`);
      return;
    }
    fn(v);
  }

  array(v: unknown, path: string, fn: (item: unknown, p: string) => void): void {
    if (!Array.isArray(v)) {
      this.errors.push(`${path}: not an array`);
      return;
    }
    v.forEach((item, i) => fn(item, `${path}[${i}]`));
  }
}

const RIG_STATES = new Set(["driving", "in_menu_paused", "no_data"]);
const RATINGS = new Set(["session_best", "personal_best", "normal"]);

function rigInfo(c: Checker, v: unknown, p: string) {
  c.object(v, p, (o) => {
    c.field(o, "rig_id", isStr, p);
    c.field(o, "name", isStr, p);
    c.field(o, "colour", (x) => isStr(x) && /^#[0-9a-fA-F]{6}$/.test(x as string), p);
    c.field(o, "address", isStr, p);
    c.field(o, "game", isStr, p);
    c.field(o, "data_format", orNull(isStr), p);
    c.field(o, "format_supported", isBool, p);
  });
}

function status(c: Checker, v: unknown, p: string) {
  c.object(v, p, (o) => {
    c.field(o, "format_mismatch", isBool, p);
    c.field(o, "formats", isObj, p);
    c.field(o, "recorder", (x) => x === null || isObj(x), p);
    c.array(o.warnings, `${p}.warnings`, (w, wp) =>
      c.object(w, wp, (wo) => {
        c.field(wo, "code", isStr, wp);
        c.field(wo, "message", isStr, wp);
        c.field(wo, "rig_id", orNull(isStr), wp);
      }),
    );
  });
}

function session(c: Checker, v: unknown, p: string) {
  c.object(v, p, (o) => {
    for (const k of ["session_id", "track_key", "track_name", "session_type"]) c.field(o, k, orNull(isStr), p);
    c.field(o, "track_length_m", orNull(isNum), p);
  });
}

function tyre(c: Checker, v: unknown, p: string) {
  if (v === null) return;
  c.object(v, p, (o) => {
    c.field(o, "compound", isStr, p);
    c.field(o, "label", isStr, p);
    c.field(o, "age_laps", orNull(isInt), p);
  });
}

function sectors(c: Checker, v: unknown, p: string) {
  if (!Array.isArray(v) || v.length !== 3) {
    c.errors.push(`${p}: expected 3 sectors`);
    return;
  }
  v.forEach((s, i) => {
    if (s === null) return;
    c.object(s, `${p}[${i}]`, (o) => {
      c.field(o, "ms", isInt, `${p}[${i}]`);
      c.field(o, "rating", (x) => x === null || RATINGS.has(x as string), `${p}[${i}]`);
    });
  });
}

const triple = (v: unknown) => Array.isArray(v) && v.length === 3 && v.every(isInt);

function rigFrame(c: Checker, v: unknown, p: string) {
  c.object(v, p, (o) => {
    c.field(o, "rig_id", isStr, p);
    c.field(o, "state", (x) => RIG_STATES.has(x as string), p);
    c.field(o, "last_seen_ms", orNull(isInt), p);
    c.field(o, "driver", orNull(isStr), p);
    session(c, o.session, `${p}.session`);
    c.field(o, "position", (x) => x === null || (isObj(x) && isNum(x.x) && isNum(x.z)), p);
    for (const k of ["speed_kph", "throttle", "brake"]) c.field(o, k, orNull(isNum), p);
    for (const k of ["gear", "rpm"]) c.field(o, k, orNull(isInt), p);
    if (!("tyre" in o)) c.errors.push(`${p}.tyre: missing`);
    tyre(c, o.tyre, `${p}.tyre`);
    if (!("lap" in o)) c.errors.push(`${p}.lap: missing`);
    if (o.lap !== null && o.lap !== undefined) {
      c.object(o.lap, `${p}.lap`, (l) => {
        c.field(l, "number", isInt, `${p}.lap`);
        c.field(l, "distance_m", isNum, `${p}.lap`);
        c.field(l, "current_ms", isInt, `${p}.lap`);
        c.field(l, "last_ms", orNull(isInt), `${p}.lap`);
        c.field(l, "valid", isBool, `${p}.lap`);
        c.field(l, "sector", (x) => x === 0 || x === 1 || x === 2, `${p}.lap`);
        sectors(c, l.sectors, `${p}.lap.sectors`);
        if (l.last_sectors !== null) sectors(c, l.last_sectors, `${p}.lap.last_sectors`);
      });
    }
    if (!("best" in o)) c.errors.push(`${p}.best: missing`);
    if (o.best !== null && o.best !== undefined) {
      c.object(o.best, `${p}.best`, (b) => {
        c.field(b, "lap_ms", isInt, `${p}.best`);
        c.field(b, "sectors_ms", triple, `${p}.best`);
        c.field(b, "lap_number", isInt, `${p}.best`);
        c.field(b, "set_at", isInt, `${p}.best`);
      });
    }
  });
}

function comparison(c: Checker, v: unknown, p: string) {
  if (v === null) return;
  c.object(v, p, (o) => {
    c.field(o, "track_key", isStr, p);
    c.array(o.rigs, `${p}.rigs`, (r, rp) =>
      c.object(r, rp, (ro) => {
        c.field(ro, "rig_id", isStr, rp);
        c.field(ro, "reference_rig_id", orNull(isStr), rp);
        c.field(ro, "best_gap_ms", orNull(isInt), rp);
        c.field(ro, "live_delta_ms", orNull(isInt), rp);
      }),
    );
  });
}

function outline(c: Checker, v: unknown, p: string) {
  c.object(v, p, (o) => {
    c.field(o, "track_key", isStr, p);
    c.field(o, "track_name", orNull(isStr), p);
    c.field(o, "points", (x) => Array.isArray(x) && x.length > 2 && x.every((pt) => Array.isArray(pt) && pt.length === 2 && pt.every(isNum)), p);
    c.field(o, "source", isStr, p);
    c.field(o, "sector_starts", (x) => x === null || triple(x), p);
    c.field(o, "display", (x) => isObj(x) && isBool(x.flip_x) && isBool(x.flip_z) && isNum(x.rotate_deg), p);
  });
}

function lapRecord(c: Checker, v: unknown, p: string) {
  c.object(v, p, (o) => {
    c.field(o, "rig_id", isStr, p);
    c.field(o, "driver", orNull(isStr), p);
    c.field(o, "track_key", isStr, p);
    c.field(o, "session_id", orNull(isStr), p);
    for (const k of ["lap_number", "lap_ms", "completed_at"]) c.field(o, k, isInt, p);
    c.field(o, "sectors_ms", (x) => x === null || triple(x), p);
    for (const k of ["valid", "out_lap", "personal_best", "session_best"]) c.field(o, k, isBool, p);
    tyre(c, o.tyre, `${p}.tyre`);
  });
}

function leaderboard(c: Checker, v: unknown, p: string) {
  if (v === null) return;
  c.object(v, p, (o) => {
    c.field(o, "track_key", isStr, p);
    c.field(o, "track_name", orNull(isStr), p);
    c.field(o, "period", isStr, p);
    c.field(o, "since", orNull(isInt), p);
    c.array(o.entries, `${p}.entries`, (e, ep) =>
      c.object(e, ep, (eo) => {
        for (const k of ["rank", "lap_ms", "gap_ms", "lap_number", "set_at"]) c.field(eo, k, isInt, ep);
        c.field(eo, "rig_id", isStr, ep);
        c.field(eo, "rig_name", isStr, ep);
        c.field(eo, "driver", orNull(isStr), ep);
        c.field(eo, "sectors_ms", (x) => x === null || triple(x), ep);
        tyre(c, eo.tyre, `${ep}.tyre`);
      }),
    );
  });
}

export function validateMessage(msg: unknown): string[] {
  const c = new Checker();
  c.object(msg, "msg", (m) => {
    c.field(m, "v", (x) => x === 1, "msg");
    c.field(m, "type", isStr, "msg");
    c.field(m, "seq", isInt, "msg");
    c.field(m, "ts", isInt, "msg");
    const t = m.type;
    const p = `msg(${String(t)})`;
    switch (t) {
      case "snapshot":
        c.object(m.hub, `${p}.hub`, (h) => {
          c.field(h, "version", isStr, `${p}.hub`);
          c.field(h, "frame_hz", isNum, `${p}.hub`);
        });
        c.object(m.cafe, `${p}.cafe`, (cafe) => {
          c.field(cafe, "name", isStr, `${p}.cafe`);
          c.field(cafe, "branding", isObj, `${p}.cafe`);
        });
        status(c, m.status, `${p}.status`);
        c.array(m.rigs, `${p}.rigs`, (r, rp) => rigInfo(c, r, rp));
        c.object(m.frame, `${p}.frame`, (f) => {
          c.array(f.rigs, `${p}.frame.rigs`, (r, rp) => rigFrame(c, r, rp));
          comparison(c, f.comparison, `${p}.frame.comparison`);
        });
        c.array(m.outlines, `${p}.outlines`, (o, op) => outline(c, o, op));
        c.array(m.leaderboards, `${p}.leaderboards`, (b, bp) => leaderboard(c, b, bp));
        c.array(m.recent_laps, `${p}.recent_laps`, (l, lp) => lapRecord(c, l, lp));
        break;
      case "frame":
        c.array(m.rigs, `${p}.rigs`, (r, rp) => rigFrame(c, r, rp));
        if (!("comparison" in m)) c.errors.push(`${p}.comparison: missing`);
        comparison(c, m.comparison, `${p}.comparison`);
        break;
      case "rig_info":
        rigInfo(c, m.rig, `${p}.rig`);
        break;
      case "status":
        status(c, m.status, `${p}.status`);
        break;
      case "session_changed":
        c.field(m, "rig_id", isStr, p);
        session(c, m.session, `${p}.session`);
        break;
      case "track_outline":
        outline(c, m.outline, `${p}.outline`);
        break;
      case "lap_completed":
        lapRecord(c, m.lap, `${p}.lap`);
        break;
      case "leaderboard":
        leaderboard(c, m.leaderboard, `${p}.leaderboard`);
        break;
      default:
        c.errors.push(`${p}: unknown type`);
    }
  });
  return c.errors;
}
