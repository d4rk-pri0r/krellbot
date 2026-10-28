import type { ChangeEvent, JSX } from "react";

/**
 * Understandable UTC date/time controls for the research scored window.
 *
 * The engine consumes exact epoch milliseconds. This panel is a strict,
 * lossless view over the SAME values the advanced From/To/holdout fields
 * hold: every UTC date/time the user picks maps exactly to the integer
 * millisecond bound that is submitted, and every exact millisecond bound
 * typed in the advanced fields is shown back as its exact UTC instant.
 * No local-timezone conversion happens anywhere; all arithmetic is done
 * with Date.UTC over the literal UTC components.
 */

const DATETIME_LOCAL_RE =
  /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d{1,3}))?$/;

function pad(value: number, width = 2): string {
  return String(value).padStart(width, "0");
}

/**
 * Exact integer-milliseconds -> canonical datetime-local string, in UTC.
 * Seconds are included only when non-zero, and the sub-second fraction is
 * emitted in the spec-canonical shortest form, so the controlled value
 * equals what the input normalizes it to. Nothing is rounded or shifted.
 * Milliseconds outside the JS Date range are an invalid Date and render
 * the empty field value, exactly like non-integer advanced text — never
 * a fabricated instant or a NaN component string.
 */
export function msToUtcFieldValue(ms: number): string {
  const date = new Date(ms);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  const datePart =
    `${pad(date.getUTCFullYear(), 4)}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}` +
    `T${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}`;
  if (date.getUTCSeconds() === 0 && date.getUTCMilliseconds() === 0) {
    return datePart;
  }
  const withSeconds = `${datePart}:${pad(date.getUTCSeconds())}`;
  const fraction = date.getUTCMilliseconds();
  if (fraction === 0) {
    return withSeconds;
  }
  return `${withSeconds}.${pad(fraction, 3).replace(/0+$/, "")}`;
}

/**
 * datetime-local string -> exact epoch milliseconds, or null when the text
 * is not a real UTC instant (bad month/day, rolled-over components, ...).
 * Validation is by full component round-trip, so invented dates never
 * silently resolve to a different day.
 */
export function utcFieldValueToMs(text: string): number | null {
  const match = DATETIME_LOCAL_RE.exec(text);
  if (!match) {
    return null;
  }
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const hour = Number(match[4]);
  const minute = Number(match[5]);
  const second = match[6] === undefined ? 0 : Number(match[6]);
  const fraction = match[7] === undefined ? 0 : Number(match[7].padEnd(3, "0"));
  const ms = Date.UTC(year, month - 1, day, hour, minute, second, fraction);
  if (!Number.isSafeInteger(ms)) {
    return null;
  }
  const check = new Date(ms);
  if (
    check.getUTCFullYear() !== year ||
    check.getUTCMonth() !== month - 1 ||
    check.getUTCDate() !== day ||
    check.getUTCHours() !== hour ||
    check.getUTCMinutes() !== minute ||
    check.getUTCSeconds() !== second ||
    check.getUTCMilliseconds() !== fraction
  ) {
    return null;
  }
  return ms;
}

export type DateBoundFieldProps = {
  id: string;
  label: string;
  /** Exact epoch-milliseconds text held by the advanced field. */
  msText: string;
  /** Datetime-local text to display when the UTC control was edited last. */
  utcText: string;
  editedUtcLast: boolean;
  onUtcChange(text: string): void;
};

function DateBoundField({
  id,
  label,
  msText,
  utcText,
  editedUtcLast,
  onUtcChange,
}: DateBoundFieldProps): JSX.Element {
  const showInvalid = editedUtcLast && utcText !== "" && msText === "";
  return (
    <label className="kbot-research__field" htmlFor={id}>
      <span className="kbot-research__field-label">{label}</span>
      <input
        id={id}
        className="kbot-research__input kbot-research__input--utc"
        type="datetime-local"
        step="0.001"
        value={editedUtcLast ? utcText : utcTextFromMsText(msText)}
        onChange={(event: ChangeEvent<HTMLInputElement>) =>
          onUtcChange(event.target.value)
        }
        autoComplete="off"
        spellCheck={false}
        aria-invalid={showInvalid}
        aria-describedby={showInvalid ? `${id}-problem` : undefined}
      />
      {showInvalid ? (
        <span
          className="kbot-research__utc-invalid"
          data-testid={`${id}-invalid`}
          id={`${id}-problem`}
        >
          Enter a valid UTC date/time
        </span>
      ) : null}
    </label>
  );
}

function utcTextFromMsText(msText: string): string {
  const trimmed = msText.trim();
  if (!/^-?\d+$/.test(trimmed)) {
    return "";
  }
  const parsed = Number(trimmed);
  if (!Number.isSafeInteger(parsed)) {
    return "";
  }
  return msToUtcFieldValue(parsed);
}

export type ResearchDateWindowProps = {
  fromMsText: string;
  toMsText: string;
  holdoutFromMsText: string;
  holdoutToMsText: string;
  fromUtcText: string;
  toUtcText: string;
  holdoutFromUtcText: string;
  holdoutToUtcText: string;
  fromEditedUtcLast: boolean;
  toEditedUtcLast: boolean;
  holdoutFromEditedUtcLast: boolean;
  holdoutToEditedUtcLast: boolean;
  onFromUtcChange(text: string): void;
  onToUtcChange(text: string): void;
  onHoldoutFromUtcChange(text: string): void;
  onHoldoutToUtcChange(text: string): void;
};

export function ResearchDateWindow({
  fromMsText,
  toMsText,
  holdoutFromMsText,
  holdoutToMsText,
  fromUtcText,
  toUtcText,
  holdoutFromUtcText,
  holdoutToUtcText,
  fromEditedUtcLast,
  toEditedUtcLast,
  holdoutFromEditedUtcLast,
  holdoutToEditedUtcLast,
  onFromUtcChange,
  onToUtcChange,
  onHoldoutFromUtcChange,
  onHoldoutToUtcChange,
}: ResearchDateWindowProps): JSX.Element {
  const fromMs = utcFieldValueToMs(fromUtcText);
  const toMs = utcFieldValueToMs(toUtcText);
  const orderingInverted =
    fromMs !== null &&
    toMs !== null &&
    fromEditedUtcLast &&
    toEditedUtcLast &&
    fromMs > toMs;
  return (
    <div
      className="kbot-research__date-window"
      data-testid="research-date-window"
    >
      <h2 className="kbot-research__date-window-title">
        UTC date/time window
      </h2>
      <p className="kbot-research__date-window-note">
        All fields are UTC. From and To are the inclusive bounds of the scored
        window; the exact millisecond instants below are what the engine
        receives. Holdout bounds are optional but must be set as a pair.
      </p>
      <DateBoundField
        id="kbot-research-utc-from"
        label="From (UTC)"
        msText={fromMsText}
        utcText={fromUtcText}
        editedUtcLast={fromEditedUtcLast}
        onUtcChange={onFromUtcChange}
      />
      <DateBoundField
        id="kbot-research-utc-to"
        label="To (UTC)"
        msText={toMsText}
        utcText={toUtcText}
        editedUtcLast={toEditedUtcLast}
        onUtcChange={onToUtcChange}
      />
      <DateBoundField
        id="kbot-research-holdout-utc-start"
        label="Holdout start (UTC)"
        msText={holdoutFromMsText}
        utcText={holdoutFromUtcText}
        editedUtcLast={holdoutFromEditedUtcLast}
        onUtcChange={onHoldoutFromUtcChange}
      />
      <DateBoundField
        id="kbot-research-holdout-utc-end"
        label="Holdout end (UTC)"
        msText={holdoutToMsText}
        utcText={holdoutToUtcText}
        editedUtcLast={holdoutToEditedUtcLast}
        onUtcChange={onHoldoutToUtcChange}
      />
      {orderingInverted ? (
        <p
          className="kbot-research__utc-ordering"
          data-testid="research-date-window-ordering"
        >
          From (UTC) is after To (UTC). Run is refused until the inclusive
          window is ordered.
        </p>
      ) : null}
    </div>
  );
}
