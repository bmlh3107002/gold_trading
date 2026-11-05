import { Info } from "lucide-react";
import { useId } from "react";

/** Tooltip giải thích chỉ số; mở bằng hover hoặc focus bàn phím. */
export function InfoTip({ label, text }: { label: string; text: string }) {
  const id = useId();
  return (
    <span className="tip">
      <button type="button" className="tip__trigger" aria-label={label} aria-describedby={id}>
        <Info size={13} aria-hidden="true" />
      </button>
      <span role="tooltip" id={id} className="tip__bubble">
        {text}
      </span>
    </span>
  );
}
