import type { EdgeRefusal } from "./edges";

type EdgeRefusalNoticeProps = {
  reason: EdgeRefusal;
  onDismiss: () => void;
};

export function EdgeRefusalNotice({
  reason,
  onDismiss,
}: EdgeRefusalNoticeProps) {
  return (
    <div role="alert">
      <p>{reason}</p>
      <button type="button" onClick={onDismiss}>
        Dismiss edge refusal
      </button>
    </div>
  );
}