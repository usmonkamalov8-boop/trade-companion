// Trade tab shell: top-level Futures / Spot switch (Binance-style), Wallet and Statistics entry points.
import 'package:flutter/material.dart';
import 'futures_trade_view.dart';
import 'order_ticket.dart';
import 'spot_trade_view.dart';
import 'stats.dart';
import 'wallet.dart';

class TradePage extends StatefulWidget {
  const TradePage({super.key});
  @override
  State<TradePage> createState() => _TradePageState();
}

class _TradePageState extends State<TradePage> with SingleTickerProviderStateMixin {
  late TabController market;
  final futuresKey = GlobalKey<FuturesTradeViewState>();
  final spotKey = GlobalKey<SpotTradeViewState>();

  @override
  void initState() {
    super.initState();
    market = TabController(length: 2, vsync: this);
    market.addListener(() => setState(() {}));
  }

  @override
  void dispose() {
    market.dispose();
    super.dispose();
  }

  void _refresh() {
    futuresKey.currentState?.load();
    spotKey.currentState?.load();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Trade'),
        bottom: TabBar(controller: market, tabs: const [Tab(text: 'Futures'), Tab(text: 'Spot')]),
        actions: [
          IconButton(onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const WalletPage())), icon: const Icon(Icons.account_balance_wallet_outlined), tooltip: 'Wallet'),
          IconButton(onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const StatsPage())), icon: const Icon(Icons.bar_chart), tooltip: 'Statistics'),
          IconButton(onPressed: _refresh, icon: const Icon(Icons.refresh)),
        ],
      ),
      floatingActionButton: market.index == 0
          ? FloatingActionButton.extended(
              icon: const Icon(Icons.add),
              label: const Text('New order'),
              onPressed: () async {
                await Navigator.push(context, MaterialPageRoute(builder: (_) => const OrderTicketPage(startTab: 0)));
                _refresh();
              },
            )
          : FloatingActionButton.extended(
              icon: const Icon(Icons.grid_view),
              label: const Text('New grid'),
              onPressed: () async {
                await Navigator.push(context, MaterialPageRoute(builder: (_) => const OrderTicketPage(startTab: 1)));
                _refresh();
              },
            ),
      body: TabBarView(controller: market, children: [
        FuturesTradeView(key: futuresKey),
        SpotTradeView(key: spotKey),
      ]),
    );
  }
}
