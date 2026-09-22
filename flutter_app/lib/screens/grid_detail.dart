// Analytics for one running or stopped spot grid.
import 'dart:async';
import 'package:flutter/material.dart';
import '../api.dart';
import '../theme.dart';

class GridDetailPage extends StatefulWidget {
  final String id;
  const GridDetailPage({super.key, required this.id});
  @override
  State<GridDetailPage> createState() => _GridDetailPageState();
}

class _GridDetailPageState extends State<GridDetailPage> {
  Map<String, dynamic>? d;
  String? err;
  Timer? timer;

  @override
  void initState() {
    super.initState();
    _load();
    timer = Timer.periodic(const Duration(seconds: 6), (_) => _load());
  }

  @override
  void dispose() {
    timer?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final r = await Api.get('/api/trade/grid/${widget.id}');
      if (mounted) setState(() => d = r);
    } catch (e) {
      if (mounted) setState(() => err = '$e');
    }
  }

  Future<void> _stop(bool sell) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Stop grid'),
        content: Text(sell ? 'Cancels the open orders and sells the coins the grid is holding at market.' : 'Cancels the open orders and keeps the coins it is holding.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Stop')),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await Api.post('/api/trade/grid/${widget.id}/stop', {'sell_inventory': sell});
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$e')));
    }
    _load();
  }

  @override
  Widget build(BuildContext context) {
    final p = context.pal;
    final v = d;
    return Scaffold(
      appBar: AppBar(title: Text(v == null ? 'Grid' : '${v['symbol']} grid')),
      body: v == null
          ? (err != null ? Center(child: Text(err!, style: TextStyle(color: p.loss))) : const Center(child: CircularProgressIndicator()))
          : ListView(padding: const EdgeInsets.all(12), children: [
              Panel(
                child: Row(children: [
                  _metric(p, 'Price', '${v['price']}'),
                  _metric(p, 'PnL', (v['total_pnl'] as num).toStringAsFixed(2), color: (v['total_pnl'] as num) >= 0 ? p.gain : p.loss),
                  _metric(p, 'vs hold', (v['vs_hold'] as num).toStringAsFixed(2), color: (v['vs_hold'] as num) >= 0 ? p.gain : p.loss),
                ]),
              ),
              Panel(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('${v['range']['lower']} - ${v['range']['upper']}   (${v['range']['status']})', style: numStyle),
                  Text('${v['cycles']} cycles, grid profit ${(v['grid_profit'] as num).toStringAsFixed(2)}, fees ${(v['fees'] as num).toStringAsFixed(2)}'),
                  if (v['apr_pct'] != null) Text('Annualised so far: ${(v['apr_pct'] as num).toStringAsFixed(0)}%  (${v['running_days'].toStringAsFixed(1)} days running)', style: TextStyle(color: p.muted)),
                  Text('Inventory ${(v['inventory_qty'] as num).toStringAsFixed(6)} (worth ${(v['inventory_value'] as num).toStringAsFixed(2)})', style: TextStyle(color: p.muted)),
                ]),
              ),
              if (v['status'] == 'running')
                Panel(
                  child: Row(children: [
                    OutlinedButton(onPressed: () => _stop(false), child: const Text('Stop (keep coins)')),
                    const SizedBox(width: 8),
                    OutlinedButton(onPressed: () => _stop(true), child: const Text('Stop and sell')),
                  ]),
                )
              else
                Panel(child: Text('Stopped: ${v['stop_reason'] ?? '-'}', style: TextStyle(color: p.muted))),
              const Heading('Open orders'),
              for (final o in (v['open_orders'] as List))
                Panel(
                  child: ListTile(
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    title: Text('${o['side']} ${o['price']}', style: numStyle),
                    trailing: Text('${(o['distance_pct'] as num).toStringAsFixed(2)}%', style: TextStyle(color: p.muted)),
                  ),
                ),
              const Heading('Recent cycles'),
              for (final c in (v['last_cycles'] as List))
                Panel(
                  child: ListTile(
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    title: Text('${c['buy_price']} -> ${c['sell_price']}', style: numStyle),
                    trailing: Text('+${(c['profit'] as num).toStringAsFixed(3)}', style: TextStyle(color: p.gain)),
                  ),
                ),
            ]),
    );
  }

  Widget _metric(Pal p, String label, String value, {Color? color}) => Expanded(
        child: Column(children: [
          Text(label, style: TextStyle(color: p.muted, fontSize: 12)),
          Text(value, style: numStyle.copyWith(fontSize: 16, fontWeight: FontWeight.w700, color: color)),
        ]),
      );
}
