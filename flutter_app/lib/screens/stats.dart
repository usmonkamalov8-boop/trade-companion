// Trades Statistics Dashboard: futures PnL/win-rate/holding-time and grid cycle performance.
import 'package:flutter/material.dart';
import '../api.dart';
import '../theme.dart';

class StatsPage extends StatefulWidget {
  const StatsPage({super.key});
  @override
  State<StatsPage> createState() => _StatsPageState();
}

class _StatsPageState extends State<StatsPage> {
  Map<String, dynamic>? d;
  String? err;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final r = await Api.get('/api/trade/stats');
      if (mounted) setState(() { d = r; err = null; });
    } catch (e) {
      if (mounted) setState(() => err = '$e');
    }
  }

  String _hold(num? seconds) {
    if (seconds == null) return '-';
    final s = seconds.round();
    if (s < 60) return '${s}s';
    final m = s ~/ 60;
    if (m < 60) return '${m}m';
    final h = m ~/ 60;
    if (h < 24) return '${h}h ${m % 60}m';
    final days = h ~/ 24;
    return '${days}d ${h % 24}h';
  }

  String _ago(num? ts) {
    if (ts == null) return '-';
    final dt = DateTime.fromMillisecondsSinceEpoch((ts * 1000).round());
    return '${dt.month}/${dt.day} ${dt.hour.toString().padLeft(2, '0')}:${dt.minute.toString().padLeft(2, '0')}';
  }

  @override
  Widget build(BuildContext context) {
    final p = context.pal;
    return Scaffold(
      appBar: AppBar(title: const Text('Statistics'), actions: [IconButton(onPressed: _load, icon: const Icon(Icons.refresh))]),
      body: err != null
          ? Center(child: Padding(padding: const EdgeInsets.all(16), child: Text(err!, style: TextStyle(color: p.loss))))
          : d == null
              ? const Center(child: CircularProgressIndicator())
              : RefreshIndicator(onRefresh: _load, child: ListView(padding: const EdgeInsets.all(12), children: _content(p, d!))),
    );
  }

  List<Widget> _content(Pal p, Map<String, dynamic> d) {
    final f = d['futures'] as Map<String, dynamic>;
    final g = d['grid'] as Map<String, dynamic>;
    final combined = (d['combined_pnl_total'] as num).toDouble();
    return [
      Panel(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('Combined PnL', style: TextStyle(color: p.muted, fontSize: 12)),
          Text('${combined >= 0 ? '+' : ''}${combined.toStringAsFixed(2)} USDT',
              style: numStyle.copyWith(fontSize: 26, fontWeight: FontWeight.w800, color: combined >= 0 ? p.gain : p.loss)),
          Text('futures ${(f['pnl_total'] as num).toStringAsFixed(2)}   grid ${(g['total_profit'] as num).toStringAsFixed(2)}', style: TextStyle(color: p.muted, fontSize: 12)),
        ]),
      ),
      const Heading('Futures'),
      Panel(
        child: Row(children: [
          _metric(p, 'Trades', '${f['closed_trades']}'),
          _metric(p, 'Win rate', f['win_rate'] == null ? '-' : '${(f['win_rate'] as num).toStringAsFixed(0)}%'),
          _metric(p, 'Avg hold', _hold(f['avg_hold_seconds'] as num?)),
          _metric(p, 'Open now', '${f['open_positions']}'),
        ]),
      ),
      Panel(
        child: Row(children: [
          _metric(p, 'Wins', '${f['wins']}', color: p.gain),
          _metric(p, 'Losses', '${f['losses']}', color: p.loss),
          _metric(p, 'Avg / trade', (f['pnl_avg'] == null) ? '-' : (f['pnl_avg'] as num).toStringAsFixed(2), color: (f['pnl_avg'] ?? 0) >= 0 ? p.gain : p.loss),
          _metric(p, 'Fees paid', (f['fees_total'] as num).toStringAsFixed(2)),
        ]),
      ),
      if ((f['by_symbol'] as List).isNotEmpty) ...[
        const Heading('By symbol (futures)'),
        Panel(
          child: Column(
            children: [
              for (final x in (f['by_symbol'] as List))
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 4),
                  child: Row(children: [
                    Expanded(child: Text(x['symbol'], style: const TextStyle(fontWeight: FontWeight.w600))),
                    Text('${x['trades']} trades', style: TextStyle(color: p.muted, fontSize: 12)),
                    const SizedBox(width: 10),
                    Text(x['win_rate'] == null ? '-' : '${(x['win_rate'] as num).toStringAsFixed(0)}% wr', style: TextStyle(color: p.muted, fontSize: 12)),
                    const SizedBox(width: 10),
                    SizedBox(
                      width: 74,
                      child: Text('${(x['pnl'] as num) >= 0 ? '+' : ''}${(x['pnl'] as num).toStringAsFixed(2)}',
                          textAlign: TextAlign.right, style: numStyle.copyWith(fontWeight: FontWeight.w700, color: (x['pnl'] as num) >= 0 ? p.gain : p.loss)),
                    ),
                  ]),
                ),
            ],
          ),
        ),
      ],
      if ((f['history'] as List).isNotEmpty) ...[
        const Heading('Trade history'),
        for (final t in (f['history'] as List)) _tradeRow(p, t),
      ],
      const Heading('Spot grid'),
      Panel(
        child: Row(children: [
          _metric(p, 'Running', '${g['running']}'),
          _metric(p, 'Stopped', '${g['stopped']}'),
          _metric(p, 'Cycles', '${g['total_cycles']}'),
          _metric(p, 'Profit', (g['total_profit'] as num).toStringAsFixed(2), color: (g['total_profit'] as num) >= 0 ? p.gain : p.loss),
        ]),
      ),
      if ((g['by_symbol'] as List).isNotEmpty) ...[
        const Heading('By symbol (grid)'),
        Panel(
          child: Column(
            children: [
              for (final x in (g['by_symbol'] as List))
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 4),
                  child: Row(children: [
                    Expanded(child: Text(x['symbol'], style: const TextStyle(fontWeight: FontWeight.w600))),
                    Text('${x['cycles']} cycles', style: TextStyle(color: p.muted, fontSize: 12)),
                    const SizedBox(width: 10),
                    Text('+${(x['profit'] as num).toStringAsFixed(2)}', style: numStyle.copyWith(fontWeight: FontWeight.w700, color: p.gain)),
                  ]),
                ),
            ],
          ),
        ),
      ],
      if ((g['history'] as List).isNotEmpty) ...[
        const Heading('Recent cycles'),
        for (final c in (g['history'] as List))
          Panel(
            child: ListTile(
              dense: true,
              contentPadding: EdgeInsets.zero,
              title: Text('${c['symbol']}  ${c['buy_price']} -> ${c['sell_price']}', style: numStyle),
              subtitle: Text(_ago(c['ts'] as num?), style: TextStyle(color: p.muted, fontSize: 11)),
              trailing: Text('+${(c['profit'] as num).toStringAsFixed(3)}', style: TextStyle(color: p.gain, fontWeight: FontWeight.w700)),
            ),
          ),
      ],
      const SizedBox(height: 24),
    ];
  }

  Widget _metric(Pal p, String label, String value, {Color? color}) => Expanded(
        child: Column(children: [
          Text(label, style: TextStyle(color: p.muted, fontSize: 12)),
          Text(value, style: numStyle.copyWith(fontSize: 15, fontWeight: FontWeight.w700, color: color)),
        ]),
      );

  Widget _tradeRow(Pal p, Map<String, dynamic> t) {
    final pnl = (t['pnl'] as num).toDouble();
    final long = t['side'] == 'LONG';
    return Panel(
      child: Row(children: [
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
          decoration: BoxDecoration(color: (long ? p.gain : p.loss).withAlpha(40), borderRadius: BorderRadius.circular(5)),
          child: Text(t['side'], style: TextStyle(color: long ? p.gain : p.loss, fontSize: 10, fontWeight: FontWeight.w700)),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(t['symbol'], style: const TextStyle(fontWeight: FontWeight.w600)),
            Text('${t['entry']} -> ${t['exit'] ?? '-'}   ${t['reason'] ?? ''}   ${_hold(t['hold_seconds'] as num?)}   ${_ago(t['closed_ts'] as num?)}',
                style: TextStyle(color: p.muted, fontSize: 11)),
          ]),
        ),
        Text('${pnl >= 0 ? '+' : ''}${pnl.toStringAsFixed(2)}', style: numStyle.copyWith(fontWeight: FontWeight.w700, color: pnl >= 0 ? p.gain : p.loss)),
      ]),
    );
  }
}
