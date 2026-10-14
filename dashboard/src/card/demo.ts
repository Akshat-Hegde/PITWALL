import { buildTrack } from "../mock/track";
import type { RaceStoryCard, StoryCard } from "../schema";

/** A sample card for demos (/card/demo) and the mock's QR codes; no hub needed. */
export function demoCard(): StoryCard {
  const track = buildTrack();
  const step = Math.max(1, Math.floor(track.points.length / 360));
  const ratings = ["purple", "green", "green", "yellow", "purple", "green", "yellow", "green"];
  return {
    token: "demo",
    created_at: Date.now(),
    driver: "Maya R",
    rig_name: "Rig 2",
    track_key: "F1:900",
    track_name: "Practice circuit",
    cafe: { name: "Sim Racing Cafe", branding: {} },
    session_minutes: 20,
    laps: 9,
    best_ms: 87_259,
    best_sectors_ms: [27_910, 31_934, 27_415],
    best_lap_class: "pro",
    theoretical_ms: 86_904,
    top_speed_kph: 318,
    today_position: 1,
    today_drivers: 14,
    today_record_ms: 87_259,
    improvement: { previous_best_ms: 88_120, delta_ms: -861 },
    minis: Array.from({ length: 24 }, (_, i) => ({ ms: 3600 + ((i * 37) % 300), rating: ratings[i % ratings.length]! })),
    outline: {
      points: track.points.filter((_, i) => i % step === 0).map(([x, z]) => [Math.round(x), Math.round(z)]),
      display: { flip_x: false, flip_z: false, rotate_deg: 0 },
    },
  };
}

/** A sample race card (/card/demo-race): P4 from P7 on the grid, best of 4 cafe drivers. */
export function demoRaceCard(): RaceStoryCard {
  return {
    kind: "race",
    token: "demo-race",
    created_at: Date.now(),
    driver: "Maya R",
    rig_name: "Rig 2",
    track_key: "F1:900",
    track_name: "Practice circuit",
    cafe: { name: "Sim Racing Cafe", branding: {} },
    session_type: "Race",
    position: 4,
    grid_position: 7,
    positions_gained: 3,
    laps: 5,
    best_ms: 87_259,
    best_lap_ms: 87_259,
    total_time_s: 462.315,
    penalties_s: 0,
    status: "finished",
    num_cars: 20,
    cafe_rank: 1,
    cafe_drivers: 4,
  };
}
