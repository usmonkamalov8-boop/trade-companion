// Trade tab shell: top-level Futures / Spot switch (Binance-style), a tappable Paper/Live badge next to the
// tabs, and the Wallet and Statistics entry points.
import 'dart:async';
import 'package:flutter/material.dart';
import '../api.dart';
import '../theme.dart';
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
  Map<String, dynamic>? envStatus;
  Timer? envTimer;
  bool switching = false;

  @override
  void initState() {
    super.initState();
    market = TabController(length: 2, vsync: this);
    market.addListener(() => setState(() {}));
    _loadEnv();
    envTimer = Timer.periodic(const Duration(seconds: 5), (_) => _loadEnv());
  }

  @override
  void dispose() {
    envTimer?.cancel();
    market.dispose();
    super.dispose();
  }

  Future<void> _loadEnv() async {
    try {
      final s = await Api.get('/api/trade/status');
      if (mounted) setState(() => envStatus = s);
    } catch (_) {
      // the top badge just keeps showing the last known state; FuturesTradeView surfaces the connection error itself
    }
  }

  void _refresh() {
    futuresKey.currentState?.load();
    spotKey.currentState?.load();
    _loadEnv();
  }

  void _toast(String m) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));
  }

  Future<void> _doSwitch(String mode, {required bool confirm}) async {
    setState(() => switching = true);
    try {
      final r = await Api.post('/api/trade/env', {'mode': mode, 'confirm': confirm});
      if (r['ok'] == true) {
        if (mode == 'live') {
          final armed = r['armed'] == true;
          _toast(armed ? 'Now trading LIVE and armed.' : 'Switched to LIVE but not armed: ${((r['problems'] as List?) ?? []).join('; ')}');
        } else {
          _toast('Switched to Paper mode.');
        }
      } else {
        _toast('${r['error']}');
      }
    } catch (e) {
      _toast('$e');
    } finally {
      if (mounted) setState(() => switching = false);
    }
    _refresh();
  }

  Future<void> _confirmToPaper() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Switch to Paper mode?'),
        content: const Text('New orders will use simulated money again. This does not close any real positions '
            'already open on Binance - flatten first from the Futures tab if you want those closed too.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Switch to Paper')),
        ],
      ),
    );
    if (ok == true) await _doSwitch('paper', confirm: false);
  }

  Future<void> _confirmToLive() async {
    Map<String, dynamic>? check;
    try {
      check = await Api.get('/api/trade/env/check', {'mode': 'live'});
    } catch (e) {
      check = {'ok': false, 'problems': ['$e'], 'warnings': []};
    }
    if (!mounted) return;
    final problems = ((check?['problems'] as List?) ?? []).cast<String>();
    final warnings = ((check?['warnings'] as List?) ?? []).cast<String>();
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) {
        final p = context.pal;
        return AlertDialog(
          title: const Text('Switch to Live trading?'),
          content: SingleChildScrollView(
            child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('Real funds will be used. Orders placed from now on reach your actual Binance account.',
                  style: TextStyle(color: p.loss, fontWeight: FontWeight.w600)),
              if (problems.isNotEmpty) ...[
                const SizedBox(height: 12),
                Text('Not ready yet:', style: TextStyle(fontWeight: FontWeight.w700, color: p.loss)),
                for (final x in problems) Padding(padding: const EdgeInsets.only(top: 2), child: Text('- $x', style: TextStyle(color: p.loss, fontSize: 12.5))),
              ],
              if (warnings.isNotEmpty) ...[
                const SizedBox(height: 12),
                for (final x in warnings) Text(x, style: TextStyle(color: p.warn, fontSize: 12.5)),
              ],
            ]),
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
            if (problems.isEmpty)
              FilledButton(
                style: FilledButton.styleFrom(backgroundColor: p.loss, foregroundColor: Colors.white),
                onPressed: () => Navigator.pop(ctx, true),
                child: const Text('Switch to Live'),
              ),
          ],
        );
      },
    );
    if (ok == true) await _doSwitch('live', confirm: true);
  }

  Widget _envBadge(Pal p) {
    final env = (envStatus?['env'] ?? 'paper').toString();
    final live = env == 'live';
    final armed = envStatus?['armed'] == true;
    final color = live ? p.loss : p.muted;
    return InkWell(
      onTap: switching ? null : (live ? _confirmToPaper : _confirmToLive),
      borderRadius: BorderRadius.circular(7),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 5),
        decoration: BoxDecoration(color: color.withAlpha(46), borderRadius: BorderRadius.circular(7), border: Border.all(color: color)),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          if (switching)
            SizedBox(width: 11, height: 11, child: CircularProgressIndicator(strokeWidth: 2, color: color))
          else ...[
            Text(live ? 'LIVE' : env.toUpperCase(), style: TextStyle(color: color, fontSize: 11.5, fontWeight: FontWeight.w800)),
            if (live && armed) ...[const SizedBox(width: 3), Icon(Icons.lock, size: 12, color: color)],
            const SizedBox(width: 3),
            Icon(Icons.swap_horiz, size: 14, color: color),
          ],
        ]),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.pal;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Trade'),
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(48),
          child: Row(children: [
            Expanded(child: TabBar(controller: market, tabs: const [Tab(text: 'Futures'), Tab(text: 'Spot')])),
            Padding(padding: const EdgeInsets.only(right: 10), child: _envBadge(p)),
          ]),
        ),
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
