// Wallet: Spot and Futures balances kept separate, the way an exchange's own wallet screen does.
import 'dart:async';
import 'package:flutter/material.dart';
import '../api.dart';
import '../theme.dart';

class WalletPage extends StatefulWidget {
  final int startTab;
  const WalletPage({super.key, this.startTab = 0});
  @override
  State<WalletPage> createState() => _WalletPageState();
}

class _WalletPageState extends State<WalletPage> with SingleTickerProviderStateMixin {
  late TabController tab;
  Map<String, dynamic>? d;
  String? err;
  Timer? timer;

  @override
  void initState() {
    super.initState();
    tab = TabController(length: 2, vsync: this, initialIndex: widget.startTab);
    _load();
    timer = Timer.periodic(const Duration(seconds: 10), (_) => _load());
  }

  @override
  void dispose() {
    timer?.cancel();
    tab.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final r = await Api.get('/api/trade/wallet');
      if (mounted) setState(() { d = r; err = null; });
    } catch (e) {
      if (mounted) setState(() => err = '$e');
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Wallet'),
        bottom: TabBar(controller: tab, tabs: const [Tab(text: 'Spot'), Tab(text: 'Futures')]),
        actions: [IconButton(onPressed: _load, icon: const Icon(Icons.refresh))],
      ),
      body: err != null
          ? Center(child: Padding(padding: const EdgeInsets.all(16), child: Text(err!, style: TextStyle(color: context.pal.loss))))
          : d == null
              ? const Center(child: CircularProgressIndicator())
              : TabBarView(controller: tab, children: [_spot(context.pal, d!['spot']), _futures(context.pal, d!['futures'])]),
    );
  }

  Widget _spot(Pal p, Map<String, dynamic> s) {
    final rows = (s['balances'] as List).cast<Map<String, dynamic>>();
    final total = (s['total_value_usdt'] as num).toDouble();
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(padding: const EdgeInsets.all(12), children: [
        Panel(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('Estimated value', style: TextStyle(color: p.muted, fontSize: 12)),
            Text('${total.toStringAsFixed(2)} USDT', style: numStyle.copyWith(fontSize: 24, fontWeight: FontWeight.w800)),
            if (s['open_orders'] != null) Text('${s['open_orders']} open order(s)', style: TextStyle(color: p.muted, fontSize: 12)),
          ]),
        ),
        const Heading('Assets'),
        if (rows.isEmpty) Panel(child: Text('No spot balances.', style: TextStyle(color: p.muted))),
        for (final r in rows)
          Panel(
            child: Row(children: [
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('${r['asset']}', style: const TextStyle(fontWeight: FontWeight.w700)),
                  Text('free ${r['free']}   locked ${r['locked']}', style: TextStyle(color: p.muted, fontSize: 12)),
                ]),
              ),
              Text(r['value_usdt'] == null ? '-' : '${(r['value_usdt'] as num).toStringAsFixed(2)} USDT',
                  style: numStyle.copyWith(fontWeight: FontWeight.w700)),
            ]),
          ),
      ]),
    );
  }

  Widget _futures(Pal p, Map<String, dynamic> f) {
    final upnl = (f['upnl'] as num).toDouble();
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(padding: const EdgeInsets.all(12), children: [
        Panel(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('Equity', style: TextStyle(color: p.muted, fontSize: 12)),
            Text('${(f['equity'] as num).toStringAsFixed(2)} USDT', style: numStyle.copyWith(fontSize: 24, fontWeight: FontWeight.w800)),
          ]),
        ),
        Panel(
          child: Row(children: [
            _metric(p, 'Wallet balance', (f['wallet'] as num).toStringAsFixed(2)),
            _metric(p, 'Available', (f['available'] as num).toStringAsFixed(2)),
            _metric(p, 'Unrealized PnL', '${upnl >= 0 ? '+' : ''}${upnl.toStringAsFixed(2)}', color: upnl >= 0 ? p.gain : p.loss),
          ]),
        ),
      ]),
    );
  }

  Widget _metric(Pal p, String label, String value, {Color? color}) => Expanded(
        child: Column(children: [
          Text(label, style: TextStyle(color: p.muted, fontSize: 12)),
          Text(value, style: numStyle.copyWith(fontSize: 15, fontWeight: FontWeight.w700, color: color)),
        ]),
      );
}
