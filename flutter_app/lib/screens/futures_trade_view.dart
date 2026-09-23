// Futures trading: Positions / Orders / Bots (signal automation + pending confirmations) / Settings (leverage & risk defaults).
import 'dart:async';
import 'package:flutter/material.dart';
import '../api.dart';
import '../theme.dart';

class FuturesTradeView extends StatefulWidget {
  const FuturesTradeView({super.key});
  @override
  State<FuturesTradeView> createState() => FuturesTradeViewState();
}

class FuturesTradeViewState extends State<FuturesTradeView> with SingleTickerProviderStateMixin, AutomaticKeepAliveClientMixin {
  late TabController tab;
  Map<String, dynamic>? st;
  String? err;
  Timer? timer;
  bool busy = false;

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    tab = TabController(length: 4, vsync: this);
    load();
    timer = Timer.periodic(const Duration(seconds: 5), (_) => load());
  }

  @override
  void dispose() {
    timer?.cancel();
    tab.dispose();
    super.dispose();
  }

  Future<void> load() async {
    try {
      final s = await Api.get('/api/trade/status');
      if (mounted) setState(() { st = s; err = null; });
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
      load();
    }
  }

  Future<void> _resume() async {
    try {
      final r = await Api.post('/api/trade/resume', {});
      _toast(r['ok'] == true ? 'Resumed' : '${r['error']}');
    } catch (e) {
      _toast('$e');
    }
    load();
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
    load();
  }

  Future<void> _approve(String id, bool ok) async {
    try {
      await Api.post('/api/trade/proposals/$id/${ok ? 'approve' : 'reject'}');
    } catch (e) {
      _toast('$e');
    }
    load();
  }

  Future<void> _cancelOrders(String symbol) async {
    try {
      await Api.post('/api/trade/orders/cancel', {'symbol': symbol});
      _toast('Cancelled $symbol orders');
    } catch (e) {
      _toast('$e');
    }
    load();
  }

  Future<void> _saveConfig(Map<String, dynamic> patch) async {
    try {
      await Api.post('/api/trade/config', {'futures': patch});
      _toast('Saved');
    } catch (e) {
      _toast('$e');
    }
    load();
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final p = context.pal;
    final s = st;
    return Column(children: [
      if (err != null) Padding(padding: const EdgeInsets.all(8), child: Text(err!, style: TextStyle(color: p.loss))),
      if (s != null) _statusBar(p, s),
      Material(
        color: Colors.transparent,
        child: TabBar(controller: tab, isScrollable: true, tabs: const [Tab(text: 'Positions'), Tab(text: 'Orders'), Tab(text: 'Bots'), Tab(text: 'Settings')]),
      ),
      Expanded(
        child: s == null
            ? const Center(child: CircularProgressIndicator())
            : TabBarView(controller: tab, children: [_positionsTab(p, s), _ordersTab(p, s), _botsTab(p, s), _settingsTab(p, s)]),
      ),
    ]);
  }

  // The Paper/Live/Armed badge itself lives on the Trade tab's app bar (tap it there to switch modes); this
  // bar only shows trading-state flags that matter specifically here (entries stopped, panic, a blocked reason).
  Widget _statusBar(Pal p, Map<String, dynamic> s) {
    final halted = s['halted'] == true;
    final showFlags = halted || s['panic'] == true || s['blocked'] != null;
    return Container(
      padding: const EdgeInsets.fromLTRB(10, 8, 10, 4),
      child: Column(children: [
        if (showFlags)
          Row(children: [
            if (halted) _badge(p, 'ENTRIES STOPPED', p.loss),
            if (s['panic'] == true) ...[const SizedBox(width: 6), _badge(p, 'PANIC', p.loss)],
            const Spacer(),
            if (s['blocked'] != null) Icon(Icons.error_outline, color: p.loss, size: 18),
          ]),
        if (showFlags) const SizedBox(height: 6),
        SizedBox(
          width: double.infinity,
          child: Wrap(spacing: 6, runSpacing: 6, children: [
            if (halted)
              FilledButton.icon(onPressed: busy ? null : _resume, icon: const Icon(Icons.play_arrow, size: 18), label: const Text('Resume'))
            else
              OutlinedButton.icon(onPressed: busy ? null : () => _kill('stop'), icon: const Icon(Icons.pause, size: 18), label: const Text('Stop entries')),
            OutlinedButton.icon(
              style: OutlinedButton.styleFrom(foregroundColor: p.loss),
              onPressed: busy ? null : () => _kill('flatten'),
              icon: const Icon(Icons.close, size: 18),
              label: const Text('Flatten'),
            ),
            OutlinedButton.icon(
              style: OutlinedButton.styleFrom(foregroundColor: p.loss),
              onPressed: busy ? null : () => _kill('panic'),
              icon: const Icon(Icons.warning_amber, size: 18),
              label: const Text('Panic'),
            ),
          ]),
        ),
      ]),
    );
  }

  Widget _badge(Pal p, String text, Color c) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
        decoration: BoxDecoration(color: c.withAlpha(46), borderRadius: BorderRadius.circular(6), border: Border.all(color: c)),
        child: Text(text, style: TextStyle(color: c, fontSize: 11, fontWeight: FontWeight.w700)),
      );

  Widget _positionsTab(Pal p, Map<String, dynamic> s) {
    final sn = s['snapshot'] as Map<String, dynamic>?;
    final positions = (sn?['positions'] as List? ?? []);
    return RefreshIndicator(
      onRefresh: load,
      child: ListView(padding: const EdgeInsets.fromLTRB(10, 8, 10, 90), children: [
        if (positions.isEmpty) Panel(child: Text('No open positions.', style: TextStyle(color: p.muted))),
        for (final x in positions) _positionCard(p, x),
      ]),
    );
  }

  Widget _positionCard(Pal p, Map<String, dynamic> x) {
    final long = x['side'] == 'LONG';
    final upnl = (x['upnl'] as num).toDouble();
    return Panel(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Text(x['symbol'], style: const TextStyle(fontWeight: FontWeight.w700)),
          const SizedBox(width: 6),
          _badge(p, x['side'], long ? p.gain : p.loss),
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
              load();
            },
            child: const Text('Move stop'),
          ),
          TextButton(onPressed: () => _closePosition(x['symbol']), child: const Text('Close')),
        ]),
      ]),
    );
  }

  Widget _ordersTab(Pal p, Map<String, dynamic> s) {
    final sn = s['snapshot'] as Map<String, dynamic>?;
    final orders = (sn?['orders'] as List? ?? []);
    final algo = (sn?['algo'] as List? ?? []);
    return RefreshIndicator(
      onRefresh: load,
      child: ListView(padding: const EdgeInsets.fromLTRB(10, 8, 10, 90), children: [
        const Heading('Open orders'),
        if (orders.isEmpty) Panel(child: Text('No open orders.', style: TextStyle(color: p.muted))),
        for (final o in orders)
          Panel(
            child: ListTile(
              dense: true,
              contentPadding: EdgeInsets.zero,
              title: Text('${o['symbol']}  ${o['side']} ${o['type']}', style: numStyle),
              subtitle: Text('qty ${o['qty']} @ ${o['price']}${o['reduce_only'] == true ? '  reduce-only' : ''}', style: TextStyle(color: p.muted, fontSize: 12)),
              trailing: TextButton(onPressed: () => _cancelOrders(o['symbol']), child: const Text('Cancel')),
            ),
          ),
        const Heading('Stops / targets'),
        if (algo.isEmpty) Panel(child: Text('No exchange-side stop or target orders.', style: TextStyle(color: p.muted))),
        for (final a in algo)
          Panel(
            child: ListTile(
              dense: true,
              contentPadding: EdgeInsets.zero,
              title: Text('${a['symbol']}  ${a['type']}', style: numStyle),
              subtitle: Text('${a['side']} @ trigger ${a['trigger']}', style: TextStyle(color: p.muted, fontSize: 12)),
            ),
          ),
      ]),
    );
  }

  Widget _botsTab(Pal p, Map<String, dynamic> s) {
    final pending = (s['pending'] as List? ?? []);
    final cfg = s['config']?['futures'] as Map<String, dynamic>?;
    return RefreshIndicator(
      onRefresh: load,
      child: ListView(padding: const EdgeInsets.fromLTRB(10, 8, 10, 90), children: [
        Panel(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('Signal automation', style: const TextStyle(fontWeight: FontWeight.w700)),
            const SizedBox(height: 4),
            Text(
              cfg?['mode'] == 'auto'
                  ? 'Auto: risk-checked signals trade by themselves.'
                  : 'Manual: every signal asks you first (Take/Skip below).',
              style: TextStyle(color: p.muted, fontSize: 12.5),
            ),
            const SizedBox(height: 8),
            SegmentedButton<String>(
              segments: const [ButtonSegment(value: 'manual', label: Text('Manual')), ButtonSegment(value: 'auto', label: Text('Auto'))],
              selected: {cfg?['mode'] ?? 'manual'},
              onSelectionChanged: (v) => _saveConfig({'mode': v.first}),
            ),
          ]),
        ),
        if (pending.isNotEmpty) ...[
          const Heading('Waiting for you'),
          for (final x in pending) _proposalCard(p, x),
        ] else
          Panel(child: Text('No pending signal confirmations.', style: TextStyle(color: p.muted))),
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

  Widget _settingsTab(Pal p, Map<String, dynamic> s) {
    final cfg = (s['config']?['futures'] as Map<String, dynamic>?) ?? {};
    return ListView(padding: const EdgeInsets.fromLTRB(10, 8, 10, 90), children: [
      Panel(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Text('Leverage & margin', style: TextStyle(fontWeight: FontWeight.w700)),
          const SizedBox(height: 10),
          _stepper(p, 'Default leverage', cfg['default_leverage'], 1, 125, (v) => _saveConfig({'default_leverage': v})),
          _stepper(p, 'Leverage cap', cfg['max_leverage'], 1, 125, (v) => _saveConfig({'max_leverage': v})),
          const SizedBox(height: 6),
          Text('Margin type', style: TextStyle(color: p.muted, fontSize: 12)),
          const SizedBox(height: 4),
          SegmentedButton<String>(
            segments: const [ButtonSegment(value: 'ISOLATED', label: Text('Isolated')), ButtonSegment(value: 'CROSSED', label: Text('Cross'))],
            selected: {cfg['margin_type'] ?? 'ISOLATED'},
            onSelectionChanged: (v) => _saveConfig({'margin_type': v.first}),
          ),
        ]),
      ),
      Panel(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Text('Risk defaults', style: TextStyle(fontWeight: FontWeight.w700)),
          const SizedBox(height: 10),
          _stepper(p, 'Risk % per trade', cfg['risk_pct'], 0.1, 5, (v) => _saveConfig({'risk_pct': v}), step: 0.1, decimals: 1),
          _stepper(p, 'Max open positions', cfg['max_positions'], 1, 20, (v) => _saveConfig({'max_positions': v})),
          _stepper(p, 'Min signal confidence', cfg['min_confidence'], 0, 100, (v) => _saveConfig({'min_confidence': v})),
          _stepper(p, 'Max daily trades', cfg['max_daily_trades'], 1, 100, (v) => _saveConfig({'max_daily_trades': v})),
        ]),
      ),
    ]);
  }

  Widget _stepper(Pal p, String label, dynamic value, num min, num max, void Function(num) onChanged, {num step = 1, int decimals = 0}) {
    final v = (value is num) ? value : min;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(children: [
        Expanded(child: Text(label, style: const TextStyle(fontSize: 13.5))),
        IconButton(icon: const Icon(Icons.remove_circle_outline), onPressed: v <= min ? null : () => onChanged((v - step).clamp(min, max)), visualDensity: VisualDensity.compact),
        SizedBox(width: 56, child: Text(v.toStringAsFixed(decimals), textAlign: TextAlign.center, style: numStyle.copyWith(fontWeight: FontWeight.w700))),
        IconButton(icon: const Icon(Icons.add_circle_outline), onPressed: v >= max ? null : () => onChanged((v + step).clamp(min, max)), visualDensity: VisualDensity.compact),
      ]),
    );
  }
}
