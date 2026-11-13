import { useTranslation } from "react-i18next";

/**
 * Câu ghi nguồn bắt buộc theo điều khoản nhà cung cấp (ING-32, docs/thiet-ke/11-dieu-khoan-nguon.md).
 * Câu của BEA phải giữ **nguyên văn tiếng Anh** — không dịch, không sửa (để ngoài i18n có chủ ý).
 */
export const BEA_ATTRIBUTION =
  "This product uses the Bureau of Economic Analysis (BEA) Data API but is not endorsed or certified by BEA.";

export function SourceAttribution() {
  const { t } = useTranslation();
  return (
    <footer className="source-attribution" aria-label={t("attribution.label")}>
      <span>{t("attribution.fed")}</span>
      <span lang="en">{BEA_ATTRIBUTION}</span>
    </footer>
  );
}
