import type { JSX } from "react";

/**
 * Supplied outlined Krellbot wordmark (Signal + Krell Asset Pack v2,
 * contract KRELL-SIGNAL-20261010).
 *
 * The path data below is copied verbatim from
 * `src/assets/brand/krellbot-wordmark-light.svg` so the approved
 * artwork ships unchanged and loads without a network request.
 * Rendered inline (rather than as an <img>) so tests and screen
 * readers can see the same shape consumers see.
 */
export function Wordmark(): JSX.Element {
  return (
    <svg
      className="kbot-wordmark"
      width="119"
      height="19"
      viewBox="0 0 496 80"
      role="img"
      aria-label="krellbot"
      data-testid="kbot-wordmark"
    >
      <g transform="translate(0 0) scale(1.25)" fill="#A8D8D1">
        <path d="M0 0H14V64H0Z M23 32L51 0H79L47 32L79 64H51Z" />
      </g>
      <g transform="translate(114.87340425531916 77.55319148936171) scale(0.10638297872340426)">
        <path
          fill="#E9F0F5"
          d="M199 -330V-729H59V0H199V-177L255 -238L384 0H548L351 -336L535 -540H376Z M619 -540V0H759V-287C759 -369 800 -410 882 -410C897 -410 907 -409 926 -406V-548C918 -549 915 -549 909 -549C845 -549 790 -507 759 -434V-540Z M1469 -226C1470 -238 1470 -243 1470 -250C1470 -304 1462 -354 1449 -392C1413 -490 1326 -549 1217 -549C1062 -549 967 -437 967 -256C967 -83 1061 23 1214 23C1335 23 1433 -45 1464 -152H1326C1309 -109 1270 -84 1219 -84C1179 -84 1147 -101 1127 -131C1114 -151 1109 -175 1107 -226ZM1109 -319C1118 -402 1153 -442 1215 -442C1279 -442 1317 -399 1324 -319Z M1708 -729H1568V0H1708Z M1986 -729H1846V0H1986Z M2116 -729V0H2256V-55C2290 -2 2337 23 2405 23C2534 23 2632 -100 2632 -263C2632 -336 2610 -410 2574 -462C2537 -515 2471 -549 2405 -549C2337 -549 2290 -524 2256 -470V-729ZM2374 -432C2443 -432 2492 -362 2492 -262C2492 -163 2444 -94 2374 -94C2303 -94 2256 -161 2256 -265C2256 -364 2304 -432 2374 -432Z M2969 -549C2804 -549 2703 -440 2703 -263C2703 -85 2804 23 2970 23C3135 23 3237 -85 3237 -259C3237 -442 3138 -549 2969 -549ZM2970 -436C3047 -436 3097 -367 3097 -261C3097 -160 3045 -90 2970 -90C2894 -90 2843 -159 2843 -263C2843 -367 2894 -436 2970 -436Z M3580 -529H3502V-674H3362V-529H3293V-436H3362V-104C3362 -19 3407 23 3499 23C3531 23 3554 20 3580 12V-86C3566 -84 3559 -83 3548 -83C3511 -83 3502 -94 3502 -142V-436H3580Z"
        />
      </g>
    </svg>
  );
}
