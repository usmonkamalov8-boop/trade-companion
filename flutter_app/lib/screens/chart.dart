import 'package:flutter/material.dart';
import 'package:webview_flutter/webview_flutter.dart';
import '../theme.dart';

class ChartPage extends StatefulWidget {
  const ChartPage({super.key});
  @override
  State<ChartPage> createState() => _ChartPageState();
}

class _ChartPageState extends State<ChartPage> {
  static const symbols = {
    'BTC': 'BINANCE:BTCUSDT.P',
    'ETH': 'BINANCE:ETHUSDT.P',
    'SOL': 'BINANCE:SOLUSDT.P',
    'RENDER': 'BINANCE:RENDERUSDT.P',
    'INJ': 'BINANCE:INJUSDT.P',
    'FET': 'BINANCE:FETUSDT.P',
    'NEAR': 'BINANCE:NEARUSDT.P',
    'AVAX': 'BINANCE:AVAXUSDT.P',
    'EUR/USD': 'OANDA:EURUSD',
    'GBP/USD': 'OANDA:GBPUSD',
    'USD/JPY': 'OANDA:USDJPY',
    'USD/CHF': 'OANDA:USDCHF',
    'AUD/USD': 'OANDA:AUDUSD',
    'USD/CAD': 'OANDA:USDCAD',
    'Gold': 'OANDA:XAUUSD',
    'DXY': 'TVC:DXY',
  };
  String cur = 'BTC';
  late final WebViewController c;

  @override
  void initState() {
    super.initState();
    c = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setBackgroundColor(C.bg);
    _load();
  }

  void _load() {
    final sym = symbols[cur]!;
    c.loadHtmlString(
      '<html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head>'
      '<body style="margin:0;background:#0c1015"><div id="tv" style="height:100vh"></div>'
      '<script src="https://s3.tradingview.com/tv.js"></script>'
      '<script>new TradingView.widget({container_id:"tv",autosize:true,symbol:"$sym",interval:"15",'
      'timezone:"Asia/Dubai",theme:"dark",style:"1",locale:"en",allow_symbol_change:true});</script>'
      '</body></html>',
      baseUrl: 'https://www.tradingview.com/',
    );
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(
          title: DropdownButton<String>(
            value: cur,
            underline: const SizedBox.shrink(),
            items: [for (final k in symbols.keys) DropdownMenuItem(value: k, child: Text(k))],
            onChanged: (v) {
              if (v == null) return;
              setState(() => cur = v);
              _load();
            },
          ),
          actions: [IconButton(onPressed: _load, icon: const Icon(Icons.refresh))],
        ),
        body: WebViewWidget(controller: c),
      );
}
