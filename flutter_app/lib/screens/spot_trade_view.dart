// Spot trading: Holdings (quick view) / Orders / Bots (spot grid bots).
import 'dart:async';
import 'package:flutter/material.dart';
import '../api.dart';
import '../theme.dart';
import 'grid_detail.dart';
import 'order_ticket.dart';
import 'wallet.dart';

class SpotTradeView extends StatefulWidget {
  const SpotTradeView({super.key});
  @override
  State<SpotTradeView> createState() => SpotTradeViewState();
}

class SpotTradeViewState extends State<SpotTradeView> with SingleTickerProviderStateMixin, AutomaticKeepAliveClientMixin {
  late TabController tab;
  Map<String, dynamic>? wallet;
  List<dynamic> grids = [];
  String? err;
  Timer? timer;

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    tab = TabController(length: 3, vsync: this);
    load();
    timer = Timer.periodic(const Duration(seconds: 8), (_) => load());
  }

  @override
  void dispose() {
    timer?.cancel();
    tab.dispose();
    super.dispose();
  }

  Future<void> load() async {
    try {
      final w = await Api.get('/api/trade/wallet');
      final g = await Api.get('/api/trade/grids');
      if (!mounted) return;
      setState(() { wallet = w; grids = g; err = null; });
    } catch (e) {
      if (mounted) setState(() => err = '$e');
    }
  }

  void _toast(String m) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));
  }

  Future<void> _stopGrid(String gid, {required bool sell}) async {
    try {
      await Api.post('/api/trade/grid/$gid/stop', {'sell_inventory': sell});
      _toast('Grid stopped');
    } catch (e) {
      _toast('$e');
    }
    load();
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final p = context.pal;
    return Column(children: [
      if (err != null) Padding(padding: const EdgeInsets.all(8), child: Text(err!, style: TextStyle(color: p.loss))),
      Material(
        color: Colors.transparent,
        child: TabBar(controller: tab, isScrollable: true, tabs: const [Tab(text: 'Holdings'), Tab(text: 'Orders'), Tab(text: 'Bots')]),
      ),
      Expanded(
        child: (wallet == null && err == null)
            ? const Center(child: CircularProgressIndicator())
            : TabBarView(controller: tab, children: [_holdingsTab(p), _ordersTab(p), _botsTab(p)]),
      ),
    ]);
  }

  Widget _holdingsTab(Pal p) {
    final s = wallet?['spot'] as Map<String, dynamic>? ?? {};
    final rows = (s['balances'] as List? ?? []).cast<Map<String, dynamic>>();
    final total = (s['total_value_usdt'] as num?)?.toDouble() ?? 0;
    return RefreshIndicator(
      onRefresh: load,
      child: ListView(padding: const EdgeInsets.fromLTRB(10, 8, 10, 90), children: [
        Panel(
          child: Row(children: [
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('Estimated value', style: TextStyle(color: p.muted, fontSize: 12)),
                Text('${total.toStringAsFixed(2)} USDT', style: numStyle.copyWith(fontSize: 20, fontWeight: FontWeight.w800)),
              ]),
            ),
            TextButton(
              onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const WalletPage(startTab: 0))),
              child: const Text('Full wallet'),
            ),
          ]),
        ),
        if (rows.isEmpty) Panel(child: Text('No spot balances.', style: TextStyle(color: p.muted))),
        for (final r in rows.take(10))
          Panel(
            child: Row(children: [
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('${r['asset']}', style: const TextStyle(fontWeight: FontWeight.w700)),
                  Text('free ${r['free']}   locked ${r['locked']}', style: TextStyle(color: p.muted, fontSize: 12)),
                ]),
              ),
              Text(r['value_usdt'] == null ? '-' : '${(r['value_usdt'] as num).toStringAsFixed(2)} USDT', style: numStyle.copyWith(fontWeight: FontWeight.w700)),
            ]),
          ),
      ]),
    );
  }

  Widget _ordersTab(Pal p) {
    final s = wallet?['spot'] as Map<String, dynamic>? ?? {};
    final n = s['open_orders'];
    return RefreshIndicator(
      onRefresh: load,
      child: ListView(padding: const EdgeInsets.fromLTRB(10, 8, 10, 90), children: [
        Panel(
          child: Text(
            n == null ? 'Open orders could not be read.' : (n == 0 ? 'No open spot orders.' : '$n open spot order(s).'),
            style: TextStyle(color: p.muted),
          ),
        ),
        Panel(
          child: Text('Individual order tickets appear here once you place a manual spot order; for now, grid orders are managed from a grid\'s own detail screen (Bots tab).',
              style: TextStyle(color: p.muted, fontSize: 12.5)),
        ),
      ]),
    );
  }

  Widget _botsTab(Pal p) {
    final running = grids.where((g) => g['status'] == 'running').toList();
    return RefreshIndicator(
      onRefresh: load,
      child: ListView(padding: const EdgeInsets.fromLTRB(10, 8, 10, 90), children: [
        if (running.isEmpty) Panel(child: Text('No grid bot running.', style: TextStyle(color: p.muted))),
        for (final g in running)
          Panel(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              ListTile(
                contentPadding: EdgeInsets.zero,
                title: Text('${g['symbol']}  ${g['lower']} - ${g['upper']}', style: numStyle),
                subtitle: Text('${g['cycles']} cycles   profit ${(g['grid_profit'] as num).toStringAsFixed(2)}'),
                trailing: const Icon(Icons.chevron_right),
                onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => GridDetailPage(id: g['id']))).then((_) => load()),
              ),
              Row(children: [
                TextButton(onPressed: () => _stopGrid(g['id'], sell: false), child: const Text('Stop (keep coins)')),
                TextButton(onPressed: () => _stopGrid(g['id'], sell: true), child: const Text('Stop & sell')),
              ]),
            ]),
          ),
        TextButton.icon(
          onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const OrderTicketPage(startTab: 1))).then((_) => load()),
          icon: const Icon(Icons.grid_view),
          label: const Text('New spot grid bot'),
        ),
      ]),
    );
  }
}
