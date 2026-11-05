import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import vi from "./vi";

export const defaultNS = "translation";
export const resources = { vi: { translation: vi } } as const;

void i18n.use(initReactI18next).init({
  lng: "vi",
  fallbackLng: "vi",
  resources,
  defaultNS,
  interpolation: { escapeValue: false },
  returnNull: false,
});

export default i18n;
