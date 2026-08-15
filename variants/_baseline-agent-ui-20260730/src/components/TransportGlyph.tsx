import type { RouteSegment } from "@/lib/types";

import styles from "./TransportGlyph.module.css";

interface TransportGlyphProps {
  mode: RouteSegment["transport_mode"];
  moving: boolean;
  arrived: boolean;
}

const classNames = (...values: Array<string | undefined>) => (
  values.filter((value): value is string => Boolean(value)).join(" ")
);

function BoatGlyph() {
  return (
    <g className={styles.motion}>
      <path
        className={classNames(styles.silhouette, styles.indigoFill)}
        d="M4.5 28.8Q17.8 33.7 31.8 27.7L28.9 33.8Q18.2 38 7.2 34.2Z"
      />
      <path className={styles.indigoLine} d="M17.4 10.2V28.8" />
      <path className={styles.indigoLine} d="M16.8 11.6Q10.4 17.2 9.2 24.8L16.8 23.4ZM18.2 13.3Q24 17.3 27.5 23.3L18.2 24.8Z" />
      <path className={styles.inkLineFine} d="M8 31.1Q18.2 34.1 28.8 30.4M7.2 35.8Q12.8 37.2 17.5 36" />
    </g>
  );
}

function HorseGlyph() {
  return (
    <g className={styles.motion}>
      <path
        className={classNames(styles.silhouette, styles.cinnabarFill)}
        d="M7.2 22.5Q10.7 17.2 17.8 18.7L24.8 19.7 29 16.5 31.5 18.2 28.4 22.6 29.7 27.8 26.6 29.1 23.3 25.2 15 26.8 11.5 31.4 8.5 30.4 9.8 25.7Z"
      />
      <path className={styles.cinnabarLine} d="M13.8 25.7 12.5 36.7M23.2 25 25.6 36.2M10 36.9h5.4M23.1 36.7h5.2" />
      <path className={styles.cinnabarLine} d="M12.2 20Q8.2 18.8 6.4 14.8M23.8 19.5 27.2 12.8" />
      <circle className={classNames(styles.silhouette, styles.cinnabarFill)} cx="21.9" cy="9.5" r="2.7" />
      <path className={styles.cinnabarLine} d="M21.2 12.1 18.5 18.8M18.8 15.4 25 18.5" />
      <path className={styles.inkLineFine} d="M20.1 6.7 23.4 7.1" />
    </g>
  );
}

function CarriageGlyph() {
  return (
    <g className={styles.motion}>
      <path
        className={classNames(styles.silhouette, styles.inkFill)}
        d="M6.2 18.8Q7.8 12.1 18.2 11.2 28 12.2 29.6 18.8L28.2 20.5H7.5Z"
      />
      <path
        className={classNames(styles.silhouette, styles.inkFill)}
        d="M6.8 20.2H29.1L30.4 29.8H5.7Z"
      />
      <path className={styles.paperCutLine} d="M10.2 17.1Q18.1 14.3 25.8 17.1M11.8 21.9v5.4M24.7 21.9v5.4" />
      <circle className={styles.inkWheel} cx="10.4" cy="32.4" r="4.1" />
      <circle className={styles.inkWheel} cx="26" cy="32.4" r="4.1" />
      <circle className={styles.cinnabarFill} cx="10.4" cy="32.4" r="1.35" />
      <circle className={styles.cinnabarFill} cx="26" cy="32.4" r="1.35" />
      <path className={styles.inkLineFine} d="M3.2 28.6H6M30 28.6h3.1M18.2 29.8V38" />
    </g>
  );
}

function WalkGlyph() {
  return (
    <g className={styles.motion}>
      <circle className={classNames(styles.silhouette, styles.jadeFill)} cx="16.2" cy="9.4" r="3" />
      <path
        className={classNames(styles.silhouette, styles.jadeFill)}
        d="M13.4 12.6Q17 11.4 19.7 14.2L21.1 24.7 24.2 31.7 20.7 33.4 17.3 26.7 14.9 37.3 11.5 36.4 12.3 25.2 8.7 30.2 6.5 28.1 11.8 19.8Z"
      />
      <path className={styles.jadeLine} d="M12.1 19.2 20.6 18M17.5 26.9 21.9 36.8M11.7 36.6h5M20.2 37h4.8" />
      <path className={styles.inkLine} d="M26.2 10.7 24.9 38" />
      <path className={styles.inkLineFine} d="M24.3 15.7 28.5 14.4M15.2 6.1 18.7 6.9" />
    </g>
  );
}

function JourneyGlyph() {
  return (
    <g className={styles.motion}>
      <path className={styles.inkLine} d="M3.5 25.5 9.6 14.1 14.1 20.2 20.8 9.1 32.1 25.5" />
      <path className={styles.goldLine} d="M5.6 31.4Q12.2 26.8 17.4 30.4T29.8 27.7" />
      <path className={styles.inkLineFine} d="M9.7 14.1 11.3 24.8M20.8 9.1 23 24.5M5.2 35.1Q12.5 33.3 18 38" />
      <circle className={classNames(styles.silhouette, styles.cinnabarFill)} cx="18" cy="38" r="2.2" />
    </g>
  );
}

export function TransportGlyph({ mode, moving, arrived }: TransportGlyphProps) {
  return (
    <svg
      className={styles.glyph}
      viewBox="0 0 36 42"
      data-mode={mode}
      data-moving={moving}
      data-arrived={arrived}
      data-anchor="18,38"
      aria-hidden="true"
      focusable="false"
    >
      {mode === "boat" ? <BoatGlyph /> : null}
      {mode === "horse" ? <HorseGlyph /> : null}
      {mode === "carriage" ? <CarriageGlyph /> : null}
      {mode === "walk" ? <WalkGlyph /> : null}
      {mode === "journey" ? <JourneyGlyph /> : null}
      <circle className={styles.arrivalRing} cx="18" cy="38" r="3" />
    </svg>
  );
}
