// Trade tab: account snapshot, positions, kill switch, manual ticket, pending confirmations, and the spot grid list.
import 'dart:async';
import 'package:flutter/material.dart';
import '../api.dart';
import '../theme.dart';
import 'grid_detail.dart';
import 'order_ticket.dart';
import 'stats.dart';

class TradePage extends StatefulWidget {
  const TradePage({super.key});
  @override
  State<TradePage> createState() => _TradePageState();
}

class _TradePageState extends State<TradePage> {
  Map<String, dynamic>? st;
  List<dynamic> grids = [];
  String? err;
  Timer? timer;
  bool busy = false;

  @override
  void initState() {
    super.initState();
    _load();
    timer = Timer.periodic(const Duration(seconds: 5), (_) => _load());
  }

  @override
  void dispose() {
    timer?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final s = await Api.get('/api/trade/status');
      final g = await Api.get('/api/trade/grids');
      if (!mounted) return;
      setState(() {
        st = s;
        grids = g;
        err = null;
      });
    } catch (e) {
      if (mounted) setState(() => err = '$e');
    }
  }

  void _toast(String m) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));
  }

  Future<bool> _typeToConfirm(String word, String message) async {
    final c = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('Type $word to confirm'),
        content: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(message),
          const SizedBox(height: 12),
          TextField(controller: c, autofocus: true, decoration: InputDecoration(hintText: word)),
        ]),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: context.pal.loss, foregroundColor: Colors.white),
            onPressed: () => Navigator.pop(ctx, c.text.trim() == word),
            child: Text(word),
          ),
        ],
      ),
    );
    return ok == true;
  }

  Future<void> _kill(String level) async {
    if (level != 'stop' && !await _typeToConfirm(level.toUpperCase(),
        level == 'flatten' ? 'Closes every position and cancels every order on the futures account.' : 'Closes everything, stops trading and switches the futures profile off.')) {
      return;
    }
    setState(() => busy = true);
    try {
      final r = await Api.post('/api/trade/kill', {'level': level});
      final left = (r['flatten'] ?? const {})['left'] as List? ?? [];
      _toast(left.isEmpty ? '$level done' : 'STILL OPEN: ${left.join(', ')}');
    } catch (e) {
      _toast('$e');
    } finally {
      if (mounted) setState(() => busy = false);
      _load();
    }
  }

  Future<void> _resume() async {
    try {
      final r = await Api.post('/api/trade/resume', {});
      _toast(r['ok'] == true ? 'Resumed' : '${r['error']}');
    } catch (e) {
      _toast('$e');
    }
    _load();
  }

  Future<void> _closePosition(String symbol) async {
    final pct = await showDialog<double>(
      context: context,
      builder: (ctx) => SimpleDialog(title: Text('Close $symbol'), children: [
        for (final p in [25.0, 50.0, 100.0]) SimpleDialogOption(onPressed: () => Navigator.pop(ctx, p), child: Text('Close ${p.toInt()}%')),
      ]),
    );
    if (pct == null) return;
    try {
      await Api.post('/api/trade/position/close', {'symbol': symbol, 'pct': pct});
      _toast('Closed ${pct.toInt()}% of $symbol');
    } catch (e) {
      _toast('$e');
    }
    _load();
  }

  Future<void> _approve(String id, bool ok) async {
    try {
      await Api.post('/api/trade/proposals/$id/${ok ? 'approve' : 'reject'}');
    } catch (e) {
      _toast('$e');
    }
    _load();
  }

  @override
  Widget build(BuildContext context) {
    final p = context.pal;
    final s = st;
    return Scaffold(
      appBar: AppBar(title: const Text('Trade'), actions: [
        IconButton(onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const StatsPage())), icon: const Icon(Icons.bar_chart), tooltip: 'Statistics'),
        IconButton(onPressed: _load, icon: const Icon(Icons.refresh)),
      ]),
      floatingActionButton: FloatingActionButton.extended(
        icon: const Icon(Icons.add),
        label: const Text('New order'),
        onPressed: () async {
          await Navigator.push(context, MaterialPageRoute(builder: (_) => const OrderTicketPage()));
          _load();
        },
      ),
      body: RefreshIndicator(
        onRefresh: _load,
        child: ListView(padding: const EdgeInsets.fromLTRB(12, 12, 12, 90), children: [
          if (err != null) Panel(child: Text(err!, style: TextStyle(color: p.loss))),
          if (s == null && err == null) const Padding(padding: EdgeInsets.all(28), child: Center(child: CircularProgressIndicator())),
          if (s != null) ..._content(p, s),
        ]),
      ),
    );
  }

  List<Widget> _content(Pal p, Map<String, dynamic> s) {
    final sn = s['snapshot'] as Map<String, dynamic>?;
    final acc = sn?['account'] as Map<String, dynamic>?;
    final positions = (sn?['positions'] as List? ?? []);
    final pending = (s['pending'] as List? ?? []);
    final halted = s['halted'] == true;
    final env = (s['env'] ?? 'paper').toString();
    return [
      Panel(
        child: Row(children: [
          _badge(env == 'live' ? 'LIVE' : env.toUpperCase(), env == 'live' ? p.loss : p.muted),
          const SizedBox(width: 8),
          if (s['armed'] == true) _badge('ARMED', p.warn),
          if (halted) ...[const SizedBox(width: 8), _badge('ENTRIES STOPPED', p.loss)],
          if (s['panic'] == true) ...[const SizedBox(width: 8), _badge('PANIC', p.loss)],
          const Spacer(),
          if (s['blocked'] != null) Icon(Icons.error_outline, color: p.loss),
        ]),
      ),
      if (s['blocked'] != null) Panel(child: Text(s['blocked'], style: TextStyle(color: p.loss))),
      if (acc != null)
        Panel(
          child: Row(children: [
            _metric(p, 'Equity', acc['equity'].toStringAsFixed(2)),
            _metric(p, 'Available', acc['available'].toStringAsFixed(2)),
            _metric(p, 'Today', (sn!['daily_pnl'] ?? 0).toStringAsFixed(2), color: (sn['daily_pnl'] ?? 0) >= 0 ? p.gain : p.loss),
          ]),
        ),
      Panel(
        child: Wrap(spacing: 8, runSpacing: 8, children: [
          if (halted)
            FilledButton.icon(onPressed: busy ? null : _resume, icon: const Icon(Icons.play_arrow), label: const Text('Resume'))
          else
            OutlinedButton.icon(onPressed: busy ? null : () => _kill('stop'), icon: const Icon(Icons.pause), label: const Text('Stop entries')),
          OutlinedButton.icon(
            style: OutlinedButton.styleFrom(foregroundColor: p.loss),
            onPressed: busy ? null : () => _kill('flatten'),
            icon: const Icon(Icons.close),
            label: const Text('Flatten'),
          ),
          OutlinedButton.icon(
            style: OutlinedButton.styleFrom(foregroundColor: p.loss),
            onPressed: busy ? null : () => _kill('panic'),
            icon: const Icon(Icons.warning_amber),
            label: const Text('Panic'),
          ),
        ]),
      ),
      if (pending.isNotEmpty) ...[
        const Heading('Waiting for you'),
        for (final x in pending) _proposalCard(p, x),
      ],
      const Heading('Positions'),
      if (positions.isEmpty) Panel(child: Text('No open positions.', style: TextStyle(color: p.muted))),
      for (final x in positions) _positionCard(p, x),
      const Heading('Spot grids'),
      if (grids.where((g) => g['status'] == 'running').isEmpty) Panel(child: Text('No grid running.', style: TextStyle(color: p.muted))),
      for (final g in grids.where((g) => g['status'] == 'running'))
        Panel(
          child: ListTile(
            contentPadding: EdgeInsets.zero,
            title: Text('${g['symbol']}  ${g['lower']} - ${g['upper']}', style: numStyle),
            subtitle: Text('${g['cycles']} cycles  profit ${(g['grid_profit'] as num).toStringAsFixed(2)}'),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => GridDetailPage(id: g['id']))).then((_) => _load()),
          ),
        ),
      TextButton.icon(
        onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const OrderTicketPage(startTab: 1))).then((_) => _load()),
        icon: const Icon(Icons.grid_view),
        label: const Text('New spot grid'),
      ),
    ];
  }

  Widget _badge(String text, Color c) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
        decoration: BoxDecoration(color: c.withAlpha(46), borderRadius: BorderRadius.circular(6), border: Border.all(color: c)),
        child: Text(text, style: TextStyle(color: c, fontSize: 11, fontWeight: FontWeight.w700)),
      );

  Widget _metric(Pal p, String label, String value, {Color? color}) => Expanded(
        child: Column(children: [
          Text(label, style: TextStyle(color: p.muted, fontSize: 12)),
          Text(value, style: numStyle.copyWith(fontSize: 16, fontWeight: FontWeight.w700, color: color)),
        ]),
      );

  Widget _positionCard(Pal p, Map<String, dynamic> x) {
    final long = x['side'] == 'LONG';
    final upnl = (x['upnl'] as num).toDouble();
    return Panel(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Text(x['symbol'], style: const TextStyle(fontWeight: FontWeight.w700)),
          const SizedBox(width: 6),
          _badge(x['side'], long ? p.gain : p.loss),
          const Spacer(),
          Text('${upnl >= 0 ? '+' : ''}${upnl.toStringAsFixed(2)}', style: numStyle.copyWith(color: upnl >= 0 ? p.gain : p.loss, fontWeight: FontWeight.w700)),
        ]),
        const SizedBox(height: 4),
        Text('qty ${x['qty']}   entry ${x['entry']}   mark ${x['mark']}   ${x['leverage']}x ${(x['margin'] ?? '').toString().toLowerCase()}', style: TextStyle(color: p.muted, fontSize: 12)),
        Text(
          x['protected'] == true ? 'stop ${x['stop'] ?? '-'}   target ${x['tp'] ?? '-'}' : 'NO STOP ON THE EXCHANGE',
          style: TextStyle(color: x['protected'] == true ? p.muted : p.loss, fontSize: 12, fontWeight: x['protected'] == true ? FontWeight.normal : FontWeight.w700),
        ),
        const SizedBox(height: 6),
        Row(children: [
          TextButton(
            onPressed: () async {
              final c = TextEditingController(text: '${x['stop'] ?? ''}');
              final v = await showDialog<String>(
                context: context,
                builder: (ctx) => AlertDialog(
                  title: const Text('Move stop'),
                  content: TextField(controller: c, keyboardType: const TextInputType.numberWithOptions(decimal: true), autofocus: true),
                  actions: [
                    TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancel')),
                    FilledButton(onPressed: () => Navigator.pop(ctx, c.text), child: const Text('Move')),
                  ],
                ),
              );
              if (v == null || v.isEmpty) return;
              try {
                final r = await Api.post('/api/trade/position/stop', {'symbol': x['symbol'], 'price': double.parse(v)});
                _toast(r['ok'] == true ? 'Stop moved' : '${r['error']}');
              } catch (e) {
                _toast('$e');
              }
              _load();
            },
            child: const Text('Move stop'),
          ),
          TextButton(onPressed: () => _closePosition(x['symbol']), child: const Text('Close')),
        ]),
      ]),
    );
  }

  Widget _proposalCard(Pal p, Map<String, dynamic> x) {
    final intent = x['intent'] as Map<String, dynamic>? ?? {};
    final expires = DateTime.fromMillisecondsSinceEpoch(((x['expires_ts'] as num) * 1000).round());
    final left = expires.difference(DateTime.now()).inSeconds;
    return Panel(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('${x['symbol']} ${x['side']}', style: const TextStyle(fontWeight: FontWeight.w700)),
        Text('entry ${intent['price'] ?? 'market'}   stop ${intent['stop']}   target ${intent['tp']}', style: TextStyle(color: p.muted, fontSize: 12)),
        Text(left > 0 ? 'expires in ${left}s' : 'expiring', style: TextStyle(color: p.warn, fontSize: 11)),
        const SizedBox(height: 6),
        Row(children: [
          FilledButton(onPressed: () => _approve(x['id'], true), child: const Text('Take')),
          const SizedBox(width: 8),
          OutlinedButton(onPressed: () => _approve(x['id'], false), child: const Text('Skip')),
        ]),
      ]),
    );
  }
}
