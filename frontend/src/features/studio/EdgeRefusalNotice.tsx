import type { EdgeRefusal } from "./edges";
import { summarizeEdgeRefusal } from "./edgeRefusalLabel";

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
      <p>{summarizeEdgeRefusal(reason).label}</p>
      <button type="button" onClick={onDismiss}>
        Dismiss edge refusal
      </button>
    </div>
  );
}