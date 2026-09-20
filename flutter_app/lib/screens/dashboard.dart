import 'dart:async';
import 'package:flutter/material.dart';
import '../api.dart';
import '../events.dart';
import '../theme.dart';

class Dashboard extends StatefulWidget {
  const Dashboard({super.key});
  @override
  State<Dashboard> createState() => _DashboardState();
}

class _DashboardState extends State<Dashboard> {
  Map<String, dynamic>? st;
  String? err;
  Timer? timer;
  bool editing = false;
  int _seen = 0;

  @override
  void initState() {
    super.initState();
    _seen = EventService.I.lastId;
    EventService.I.addListener(_onEvent);
    _load();
    timer = Timer.periodic(const Duration(seconds: 6), (_) => _load());
  }

  @override
  void dispose() {
    EventService.I.removeListener(_onEvent);
    timer?.cancel();
    super.dispose();
  }

  // a new event usually means positions or status changed: refresh right away
  void _onEvent() {
    if (EventService.I.lastId != _seen) {
      _seen = EventService.I.lastId;
      _load();
    }
  }

  Future<void> _load() async {
    if (editing) return;
    if (!Api.ready) {
      if (mounted) setState(() => err = 'Enter your API token in Settings to connect.');
      return;
    }
    try {
      final s = await Api.get('/api/status') as Map<String, dynamic>;
      if (mounted) {
        setState(() {
          st = s;
          err = null;
        });
      }
    } catch (e) {
      if (mounted) setState(() => err = '$e');
    }
  }

  void _toast(String m) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));
  }

  Future<void> _cmd(String c) async {
    if (c == 'closeall') {
      final p = context.pal;
      final ok = await showDialog<bool>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: const Text('Close all positions?'),
          content: const Text('Every open position is closed at market and the bot is halted.'),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
            FilledButton(
              style: FilledButton.styleFrom(backgroundColor: p.loss, foregroundColor: Colors.white),
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('Close all'),
            ),
          ],
        ),
      );
      if (ok != true) return;
    }
    try {
      final r = await Api.post('/api/command/$c');
      if (r['ok'] != true) _toast('Some orders failed: ${r['results']}');
    } catch (e) {
      _toast('$e');
    }
    _load();
  }

  Future<void> _setRisk(String name, Map<String, dynamic> patch) async {
    try {
      await Api.post('/api/risk', {'profile': name, ...patch});
    } catch (e) {
      _toast('$e');
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = context.pal;
    final s = st;
    return Scaffold(
      appBar: AppBar(title: const Text('Bot'), actions: [
        ListenableBuilder(
          listenable: EventService.I,
          builder: (context, _) => IconButton(
            tooltip: 'Activity',
            onPressed: Toaster.openLog,
            icon: Badge(
              isLabelVisible: EventService.I.unread > 0,
              label: Text('${EventService.I.unread}'),
              child: const Icon(Icons.notifications_outlined),
            ),
          ),
        ),
        IconButton(onPressed: _load, icon: const Icon(Icons.refresh)),
      ]),
      body: RefreshIndicator(
        onRefresh: _load,
        child: ListView(padding: const EdgeInsets.all(12), children: [
          if (err != null) Panel(child: Text(err!, style: TextStyle(color: p.loss))),
          if (s == null && err == null)
            const Padding(padding: EdgeInsets.all(28), child: Center(child: CircularProgressIndicator())),
          if (s != null) ..._content(p, s),
        ]),
      ),
    );
  }

  Widget _metric(Pal p, String label, String value, {Color? color}) => Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label, style: TextStyle(color: p.muted, fontSize: 12)),
          const SizedBox(height: 2),
          Text(value, style: numStyle.copyWith(fontSize: 17, fontWeight: FontWeight.w600, color: color)),
        ]),
      );

  List<Widget> _content(Pal p, Map<String, dynamic> s) {
    final acc = s['account'] as Map<String, dynamic>?;
    final pnl = s['pnl'] as Map<String, dynamic>?;
    final pos = (s['positions'] as List?) ?? [];
    final profiles = s['profiles'] as Map<String, dynamic>;
    final halted = s['halted'] == true;
    ButtonStyle col(Color c, Color fg) => FilledButton.styleFrom(backgroundColor: c, foregroundColor: fg);
    return [
      Panel(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Icon(Icons.circle, size: 10, color: halted ? p.warn : p.gain),
            const SizedBox(width: 8),
            Text(halted ? 'Halted, no new entries' : 'Running', style: const TextStyle(fontWeight: FontWeight.w600)),
            const Spacer(),
            Text('service ${s['service']}', style: TextStyle(color: p.muted, fontSize: 12)),
          ]),
          const SizedBox(height: 12),
          if (acc != null)
            Row(children: [
              _metric(p, 'Balance', fnum(acc['balance'], 2)),
              _metric(p, 'Free', fnum(acc['available'], 2)),
              _metric(p, 'Unrealized', signed(acc['upnl']),
                  color: (acc['upnl'] as num) >= 0 ? p.gain : p.loss),
            ])
          else
            Text('${s['error'] ?? 'Account unavailable. Add your Binance keys to backend/.env on the VPS.'}',
                style: TextStyle(color: p.muted)),
          if (pnl != null)
            Padding(
              padding: const EdgeInsets.only(top: 10),
              child: Text(
                '7-day realized PnL ${signed(pnl['total'])} USDT  (${pnl['wins']} wins, ${pnl['losses']} losses)',
                style: TextStyle(color: p.muted, fontSize: 13),
              ),
            ),
        ]),
      ),
      Row(children: [
        Expanded(child: FilledButton(onPressed: () => _cmd('halt'), style: col(p.warn, Colors.black), child: const Text('Halt'))),
        const SizedBox(width: 8),
        Expanded(child: FilledButton(onPressed: () => _cmd('resume'), style: col(p.gain, Colors.black), child: const Text('Resume'))),
        const SizedBox(width: 8),
        Expanded(child: FilledButton(onPressed: () => _cmd('closeall'), style: col(p.loss, Colors.white), child: const Text('Close all'))),
      ]),
      const Heading('Recent activity'),
      _recent(p),
      const Heading('Open positions'),
      if (pos.isEmpty) Text('No open positions.', style: TextStyle(color: p.muted)),
      for (final x in pos) _posRow(p, x as Map<String, dynamic>),
      const Heading('Risk and profiles'),
      for (final e in profiles.entries) _riskCard(p, e.key, e.value as Map<String, dynamic>),
      const SizedBox(height: 16),
    ];
  }

  Widget _recent(Pal p) => ListenableBuilder(
        listenable: EventService.I,
        builder: (context, _) {
          final last = EventService.I.events.reversed.take(3).toList();
          return Panel(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              if (last.isEmpty)
                Text(EventService.I.connected ? 'No activity yet.' : 'Connecting to the live feed...',
                    style: TextStyle(color: p.muted)),
              for (final e in last)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 4),
                  child: Row(children: [
                    Icon(kindIcon(e.kind), size: 18, color: levelColor(p, e.level)),
                    const SizedBox(width: 8),
                    Expanded(child: Text(e.title, maxLines: 1, overflow: TextOverflow.ellipsis)),
                    const SizedBox(width: 8),
                    Text(clockText(e.ts), style: numStyle.copyWith(color: p.muted, fontSize: 12)),
                  ]),
                ),
              Align(
                alignment: Alignment.centerRight,
                child: TextButton(onPressed: Toaster.openLog, child: const Text('All activity')),
              ),
            ]),
          );
        },
      );

  Widget _posRow(Pal p, Map<String, dynamic> x) {
    final up = (x['pnl'] as num) >= 0;
    final long = x['side'] == 'LONG';
    final liq = (x['liq'] as num).toDouble();
    return Panel(
      child: Row(children: [
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              Text('${x['symbol']}', style: const TextStyle(fontWeight: FontWeight.w700)),
              const SizedBox(width: 8),
              Text('${x['side']}',
                  style: TextStyle(color: long ? p.gain : p.loss, fontWeight: FontWeight.w600, fontSize: 12)),
            ]),
            const SizedBox(height: 3),
            Text('qty ${x['qty']}   entry ${fnum(x['entry'])}   mark ${fnum(x['mark'])}',
                style: numStyle.copyWith(color: p.muted, fontSize: 12)),
            if (liq > 0) Text('liquidation ${fnum(liq)}', style: numStyle.copyWith(color: p.muted, fontSize: 12)),
          ]),
        ),
        Text(signed(x['pnl']),
            style: numStyle.copyWith(color: up ? p.gain : p.loss, fontWeight: FontWeight.w700, fontSize: 17)),
      ]),
    );
  }

  Widget _riskCard(Pal p, String name, Map<String, dynamic> x) {
    final risk = (x['risk_pct'] as num).toDouble().clamp(0.1, 3.0).toDouble();
    final maxPos = (x['max_positions'] as num).toInt();
    return Panel(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Text(name, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
          if (x['shadow'] == true)
            Padding(
              padding: const EdgeInsets.only(left: 8),
              child: Text('shadow, no orders', style: TextStyle(color: p.muted, fontSize: 12)),
            ),
          const Spacer(),
          Switch(
            value: x['enabled'] == true,
            onChanged: (v) {
              setState(() => x['enabled'] = v);
              _setRisk(name, {'enabled': v});
            },
          ),
        ]),
        Text('Risk per trade ${risk.toStringAsFixed(1)}%', style: numStyle),
        Slider(
          value: risk,
          min: 0.1,
          max: 3.0,
          divisions: 29,
          onChangeStart: (_) => editing = true,
          onChanged: (v) => setState(() => x['risk_pct'] = double.parse(v.toStringAsFixed(1))),
          onChangeEnd: (v) {
            editing = false;
            _setRisk(name, {'risk_pct': double.parse(v.toStringAsFixed(1))});
          },
        ),
        Row(children: [
          Text('Max positions $maxPos', style: numStyle),
          const Spacer(),
          IconButton(
            icon: const Icon(Icons.remove_circle_outline),
            onPressed: maxPos > 1
                ? () {
                    setState(() => x['max_positions'] = maxPos - 1);
                    _setRisk(name, {'max_positions': maxPos - 1});
                  }
                : null,
          ),
          IconButton(
            icon: const Icon(Icons.add_circle_outline),
            onPressed: maxPos < 10
                ? () {
                    setState(() => x['max_positions'] = maxPos + 1);
                    _setRisk(name, {'max_positions': maxPos + 1});
                  }
                : null,
          ),
        ]),
      ]),
    );
  }
}
