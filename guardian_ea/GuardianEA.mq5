//+------------------------------------------------------------------+
//| GuardianEA.mq5 — hàng rào cuối tại terminal MT5 (docs/09)          |
//| Quy tắc tối giản: ngưỡng equity cứng + heartbeat của Gateway.     |
//| CHƯA BIÊN DỊCH / CHƯA KIỂM THỬ — chỉ là khung, diễn tập trên demo. |
//+------------------------------------------------------------------+
#property strict
#property version   "0.10"

#include <Trade/Trade.mqh>

input string ConfigVersion        = "guardian-0.1.0";
input long   MagicNumber          = 20260101;  // chỉ đụng vào lệnh của bot
input double MinEquity            = 0.0;       // 0 = tắt; equity dưới mức này -> đóng hết
input double MaxDrawdownPct       = 5.0;       // % so với equity đỉnh trong phiên EA
input int    HeartbeatTimeoutSec  = 60;        // Gateway phải cập nhật GV "GT_HEARTBEAT"
input bool   CloseOnHeartbeatLoss = false;     // mặc định chỉ chặn, không đóng

CTrade   trade;
double   peakEquity = 0.0;
bool     tripped    = false;

int OnInit()
  {
   trade.SetExpertMagicNumber(MagicNumber);
   peakEquity = AccountInfoDouble(ACCOUNT_EQUITY);
   EventSetTimer(1);
   PrintFormat("GuardianEA %s started, peak equity %.2f", ConfigVersion, peakEquity);
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason) { EventKillTimer(); }

void OnTimer()
  {
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   if(equity > peakEquity) peakEquity = equity;

   if(!tripped && MinEquity > 0 && equity < MinEquity)
      Trip("EQUITY_BELOW_MIN", true);

   if(!tripped && peakEquity > 0 && (peakEquity - equity) / peakEquity * 100.0 >= MaxDrawdownPct)
      Trip("DRAWDOWN_LIMIT", true);

   // Heartbeat: Gateway ghi TimeCurrent() vào global variable GT_HEARTBEAT.
   if(GlobalVariableCheck("GT_HEARTBEAT"))
     {
      datetime hb = (datetime)GlobalVariableGet("GT_HEARTBEAT");
      if(TimeCurrent() - hb > HeartbeatTimeoutSec)
         Trip("HEARTBEAT_LOST", CloseOnHeartbeatLoss);
     }

   // Báo trạng thái cho Gateway/Safety: 1 = đã chặn.
   GlobalVariableSet("GT_GUARDIAN_TRIPPED", tripped ? 1.0 : 0.0);
  }

void Trip(const string reason, const bool closeAll)
  {
   if(!tripped)
      PrintFormat("GuardianEA TRIP: %s (config %s)", reason, ConfigVersion);
   tripped = true;
   if(closeAll) CloseBotPositions();
  }

void CloseBotPositions()
  {
   // Hủy lệnh chờ của bot
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      ulong ticket = OrderGetTicket(i);
      if(ticket > 0 && OrderGetInteger(ORDER_MAGIC) == MagicNumber)
         trade.OrderDelete(ticket);
     }
   // Đóng vị thế của bot
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket > 0 && PositionGetInteger(POSITION_MAGIC) == MagicNumber)
         trade.PositionClose(ticket);
     }
  }
