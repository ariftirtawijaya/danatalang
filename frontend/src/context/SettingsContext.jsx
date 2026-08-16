import { createContext, useContext, useEffect, useState, useCallback } from "react";
import { api, API } from "@/lib/api";

const SettingsContext = createContext({ settings: null, reload: () => {} });

export function SettingsProvider({ children }) {
  const [settings, setSettings] = useState(null);

  const reload = useCallback(async () => {
    try {
      const { data } = await api.get("/public/settings");
      setSettings(data);
      document.title = data.app_name ? `${data.app_name}` : "PinjamKu";
      if (data.favicon_url) {
        let link = document.querySelector("link[rel='icon']");
        if (!link) {
          link = document.createElement("link");
          link.rel = "icon";
          document.head.appendChild(link);
        }
        link.href = `${process.env.REACT_APP_BACKEND_URL}${data.favicon_url}`;
      }
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  return (
    <SettingsContext.Provider value={{ settings, reload, assetBase: API.replace(/\/api$/, "") }}>
      {children}
    </SettingsContext.Provider>
  );
}

export const useSettings = () => useContext(SettingsContext);
