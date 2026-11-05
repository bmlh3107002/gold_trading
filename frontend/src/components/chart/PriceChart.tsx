import {
  ColorType,
  CrosshairMode,
  LineStyle,
  TickMarkType,
  createChart,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type LogicalRange,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { CandleOut } from "../../api/client";
import type { Theme } from "../../hooks/useTheme";
import { formatDateTime, formatDayMonth, formatNumber, formatTime } from "../../lib/format";
import { readChartColors } from "./chartTheme";
import { toChartTimes } from "./chartTime";

interface PriceChartProps {
  candles: CandleOut[];
  ema20: (number | null)[];
  ema50: (number | null)[];
  rsi14: (number | null)[];
  theme: Theme;
  /** Hỗ trợ (S) / kháng cự (R) từ Technical analyst còn hiệu lực */
  levels?: { price: number; kind: "S" | "R" }[];
}

function line(values: (number | null)[], times: UTCTimestamp[]) {
  const out: { time: UTCTimestamp; value: number }[] = [];
  values.forEach((v, i) => {
    if (v != null) out.push({ time: times[i], value: v });
  });
  return out;
}

/** Biểu đồ nến + EMA 20/50 và khung RSI 14 đồng bộ trục thời gian. Hiển thị theo giờ máy người xem. */
export function PriceChart({ candles, ema20, ema50, rsi14, theme, levels = [] }: PriceChartProps) {
  const { t } = useTranslation();
  const priceEl = useRef<HTMLDivElement>(null);
  const rsiEl = useRef<HTMLDivElement>(null);
  const charts = useRef<{
    price: IChartApi;
    rsi: IChartApi;
    candle: ISeriesApi<"Candlestick">;
    e20: ISeriesApi<"Line">;
    e50: ISeriesApi<"Line">;
    r: ISeriesApi<"Line">;
    guides: IPriceLine[];
  } | null>(null);
  const [hover, setHover] = useState<number | null>(null);
  const levelLines = useRef<IPriceLine[]>([]);

  // Thời gian trên trục đã dời theo giờ máy người xem (xem chartTime.ts); formatter đổi ngược lại
  const chartTimes = useMemo(() => toChartTimes(candles.map((c) => c.open_time)), [candles]);
  const times = chartTimes.times;
  const toReal = useRef(chartTimes.toReal);
  toReal.current = chartTimes.toReal;
  const realDate = (tm: Time) => new Date(toReal.current(tm as number) * 1000);
  const indexByTime = useMemo(() => new Map(times.map((tm, i) => [tm as number, i])), [times]);

  // Tạo biểu đồ một lần
  useEffect(() => {
    if (!priceEl.current || !rsiEl.current) return;
    const common = {
      autoSize: true,
      crosshair: { mode: CrosshairMode.Normal },
      localization: {
        locale: "vi-VN",
        timeFormatter: (tm: Time) => formatDateTime(realDate(tm)),
        priceFormatter: (p: number) => formatNumber(p),
      },
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
        // Sang ngày mới thì hiện ngày/tháng, còn lại hiện giờ:phút (giờ máy người xem)
        tickMarkFormatter: (tm: Time, type: TickMarkType) => {
          const d = realDate(tm);
          return type <= TickMarkType.DayOfMonth ? formatDayMonth(d) : formatTime(d).slice(0, 5);
        },
      },
    };
    const price = createChart(priceEl.current, common);
    const rsi = createChart(rsiEl.current, common);
    const candle = price.addCandlestickSeries({ borderVisible: false, priceLineVisible: true });
    const e20 = price.addLineSeries({ lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    const e50 = price.addLineSeries({ lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    const r = rsi.addLineSeries({
      lineWidth: 1,
      priceLineVisible: false,
      // RSI luôn trong 0–100: cố định thang để mức 30/70 không nhảy khi cuộn
      autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 100 } }),
    });
    rsi.priceScale("right").applyOptions({ scaleMargins: { top: 0.08, bottom: 0.08 } });
    const guides = [70, 30].map((price) =>
      r.createPriceLine({ price, lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: true, title: "" }),
    );

    // Đồng bộ cuộn/zoom giữa hai khung
    let syncing = false;
    const link = (from: IChartApi, to: IChartApi) =>
      from.timeScale().subscribeVisibleLogicalRangeChange((range: LogicalRange | null) => {
        if (syncing || !range) return;
        syncing = true;
        to.timeScale().setVisibleLogicalRange(range);
        syncing = false;
      });
    link(price, rsi);
    link(rsi, price);
    price.subscribeCrosshairMove((p) => setHover(p.time == null ? null : (p.time as number)));

    charts.current = { price, rsi, candle, e20, e50, r, guides };
    return () => {
      charts.current = null;
      price.remove();
      rsi.remove();
    };
  }, []);

  // Theme
  useEffect(() => {
    const c = charts.current;
    if (!c) return;
    const col = readChartColors();
    const opts = {
      layout: {
        background: { type: ColorType.Solid, color: col.bg },
        textColor: col.text,
        fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif",
        fontSize: 11,
        attributionLogo: false, // đã ghi nguồn + link TradingView bên dưới biểu đồ
      },
      grid: { vertLines: { color: col.grid }, horzLines: { color: col.grid } },
      rightPriceScale: { borderColor: col.border },
      timeScale: { borderColor: col.border },
      crosshair: {
        vertLine: { color: col.guide, labelBackgroundColor: col.guide },
        horzLine: { color: col.guide, labelBackgroundColor: col.guide },
      },
    };
    c.price.applyOptions(opts);
    c.rsi.applyOptions(opts);
    c.candle.applyOptions({ upColor: col.up, downColor: col.down, wickUpColor: col.up, wickDownColor: col.down });
    c.e20.applyOptions({ color: col.ema20 });
    c.e50.applyOptions({ color: col.ema50 });
    c.r.applyOptions({ color: col.rsi });
    c.guides.forEach((g) => g.applyOptions({ color: col.guide }));
  }, [theme]);

  // Dữ liệu
  useEffect(() => {
    const c = charts.current;
    if (!c) return;
    c.candle.setData(
      candles.map((k, i) => ({ time: times[i], open: k.open, high: k.high, low: k.low, close: k.close })),
    );
    c.e20.setData(line(ema20, times));
    c.e50.setData(line(ema50, times));
    c.r.setData(line(rsi14, times));
  }, [candles, ema20, ema50, rsi14, times]);

  // Vẽ lại đường hỗ trợ/kháng cự khi kết quả phân tích hoặc theme đổi
  const levelKey = levels.map((l) => `${l.kind}${l.price}`).join("|");
  useEffect(() => {
    const c = charts.current;
    if (!c) return;
    levelLines.current.forEach((ln) => c.candle.removePriceLine(ln));
    const col = readChartColors();
    levelLines.current = levels.map((lv) =>
      c.candle.createPriceLine({
        price: lv.price,
        color: lv.kind === "S" ? col.up : col.down,
        lineWidth: 1,
        lineStyle: LineStyle.Dotted,
        axisLabelVisible: true,
        title: lv.kind === "S" ? t("technical.support") : t("technical.resistance"),
      }),
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [levelKey, theme, t]);

  const i = hover != null ? (indexByTime.get(hover) ?? candles.length - 1) : candles.length - 1;
  const k = candles[i];
  const up = k ? k.close >= k.open : true;

  return (
    <div className="price-chart">
      {k && (
        <dl className="chart-legend num" aria-live="off">
          <div>
            <dt>{t("market.legendTime")}</dt>
            <dd>{formatDateTime(k.open_time)}</dd>
          </div>
          {(
            [
              ["open", k.open],
              ["high", k.high],
              ["low", k.low],
              ["close", k.close],
            ] as const
          ).map(([key, v]) => (
            <div key={key}>
              <dt>{t(`market.${key}`)}</dt>
              <dd className={up ? "tone-profit" : "tone-loss"}>{formatNumber(v)}</dd>
            </div>
          ))}
          <div>
            <dt className="legend-ema20">{t("market.ema20")}</dt>
            <dd>{formatNumber(ema20[i])}</dd>
          </div>
          <div>
            <dt className="legend-ema50">{t("market.ema50")}</dt>
            <dd>{formatNumber(ema50[i])}</dd>
          </div>
        </dl>
      )}
      <div ref={priceEl} className="price-chart__main" role="img" aria-label={t("market.chartTitle")} />
      <div className="price-chart__rsi-head">
        <span className="legend-rsi">{t("market.rsi14")}</span>
        <span className="num">{formatNumber(rsi14[i])}</span>
      </div>
      <div ref={rsiEl} className="price-chart__rsi" role="img" aria-label={t("market.rsiTitle")} />
    </div>
  );
}
