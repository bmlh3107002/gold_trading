import { useTranslation } from "react-i18next";

/**
 * Câu ghi nguồn bắt buộc theo điều khoản nhà cung cấp (ING-32, docs/thiet-ke/11-dieu-khoan-nguon.md).
 * Câu của BEA, Census phải giữ **nguyên văn tiếng Anh** — không dịch, không sửa (để ngoài i18n có chủ ý).
 */
export const BEA_ATTRIBUTION =
  "This product uses the Bureau of Economic Analysis (BEA) Data API but is not endorsed or certified by BEA.";

/** Nguyên văn câu BLS yêu cầu khi dùng lại số liệu (điều khoản API BLS, đọc qua ảnh chụp 2026-11-13). */
export const BLS_DISCLAIMER =
  "BLS.gov cannot vouch for the data or analyses derived from these data after the data have been retrieved from BLS.gov.";

/** Nguyên văn theo điều khoản Census Data API (đọc 2026-11-13) — không dịch, không sửa. */
export const CENSUS_ATTRIBUTION =
  "This product uses the Census Bureau Data API but is not endorsed or certified by the Census Bureau.";

export function SourceAttribution() {
  const { t } = useTranslation();
  return (
    <footer className="source-attribution" aria-label={t("attribution.label")}>
      <span>{t("attribution.fed")}</span>
      <span>{t("attribution.dol")}</span>
      <span>
        {t("attribution.bls")} <span lang="en">{BLS_DISCLAIMER}</span>
      </span>
      <span>{t("attribution.treasury")}</span>
      <span>{t("attribution.h15")}</span>
      <span>{t("attribution.cftc")}</span>
      <span lang="en">{BEA_ATTRIBUTION}</span>
      <span lang="en">{CENSUS_ATTRIBUTION}</span>
    </footer>
  );
}
