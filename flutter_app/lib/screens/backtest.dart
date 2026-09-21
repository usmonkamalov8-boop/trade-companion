import 'dart:async';
import 'package:flutter/material.dart';
import '../api.dart';
import '../theme.dart';
import 'settings.dart' show styleLabels;

/// Replays the analyst's setups on the last months of crypto history and shows win rates and profitability.
class BacktestView extends StatefulWidget {
  const BacktestView({super.key});
  @override
  State<BacktestView> createState() => _BacktestViewState();
}

class _BacktestViewState extends State<BacktestView> with AutomaticKeepAliveClientMixin {
  int days = 90;
  String style = 'intraday';
  int fee = 5;
  Map<String, dynamic>? job;
  bool busy = false;
  String? err;
  Timer? timer;

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    if (Api.ready) {
      _poll();
    } else {
      err = 'Enter your API token in Settings to connect.';
    }
  }

  @override
  void dispose() {
    timer?.cancel();
    super.dispose();
  }

  Future<void> _poll() async {
    try {
      final j = await Api.get('/api/backtest/status') as Map<String, dynamic>;
      if (!mounted) return;
      setState(() {
        job = j;
        err = null;
      });
      final running = j['status'] == 'running';
      if (running && timer == null) {
        timer = Timer.periodic(const Duration(seconds: 4), (_) => _poll());
      } else if (!running) {
        timer?.cancel();
        timer = null;
      }
    } catch (e) {
      if (mounted) setState(() => err = '$e');
    }
  }

  Future<void> _start() async {
    setState(() {
      busy = true;
      err = null;
    });
    try {
      await Api.post('/api/backtest/start', {'days': days, 'style': style, 'fee_bp': fee.toDouble(), 'slip_bp': 2.0, 'min_conf': 0});
      await _poll();
    } catch (e) {
      if (mounted) setState(() => err = '$e');
    }
    if (mounted) setState(() => busy = false);
  }

  Future<void> _cancel() async {
    try {
      await Api.post('/api/backtest/cancel');
    } catch (_) {}
    await _poll();
  }

  String _pct(dynamic v) => v == null ? '-' : '${(v as num).toStringAsFixed(0)}%';
  String _r(dynamic v) => v == null ? '-' : '${(v as num) >= 0 ? '+' : ''}${(v as num).toStringAsFixed(2)}R';
  String _tr(dynamic v) => v == null ? '-' : '${(v as num) >= 0 ? '+' : ''}${(v as num).toStringAsFixed(1)}R';
  Color _col(Pal p, dynamic v) => v == null ? p.muted : ((v as num) > 0 ? p.gain : ((v) < 0 ? p.loss : p.muted));

  Widget _stat(Pal p, String value, String label, {Color? color}) => Expanded(
        child: Column(children: [
          Text(value, style: numStyle.copyWith(fontSize: 17, fontWeight: FontWeight.w800, color: color)),
          Text(label, style: TextStyle(color: p.muted, fontSize: 11)),
        ]),
      );

  Widget _tier(Pal p, String title, Map<String, dynamic>? s) {
    if (s == null || (s['filled'] as num) == 0) {
      return Padding(
        padding: const EdgeInsets.only(bottom: 10),
        child: Text('$title: no filled setups', style: TextStyle(color: p.muted, fontSize: 12.5)),
      );
    }
    final pf = s['profit_factor'];
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(title, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 13.5)),
        const SizedBox(height: 4),
        Row(children: [
          _stat(p, _pct(s['win_rate']), 'win rate'),
          _stat(p, _r(s['avg_net_r']), 'avg net', color: _col(p, s['avg_net_r'])),
          _stat(p, _tr(s['total_net_r']), 'total net', color: _col(p, s['total_net_r'])),
          _stat(p, pf == null ? '-' : (pf as num).toStringAsFixed(2), 'profit factor'),
        ]),
        Text('${s['filled']} trades (${s['wins']} wins, ${s['losses']} stops)  -  max drawdown ${(s['max_dd_r'] as num).toStringAsFixed(1)}R  -  fill rate ${_pct(s['fill_rate'])}',
            style: TextStyle(color: p.muted, fontSize: 11.5)),
      ]),
    );
  }

  Widget _rows(Pal p, String title, List items, {bool byAsset = false}) {
    final rows = items.where((b) => (b['filled'] as num) > 0).toList();
    if (rows.isEmpty) return const SizedBox.shrink();
    return Panel(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(title, style: TextStyle(color: p.muted, fontSize: 11, letterSpacing: 1, fontWeight: FontWeight.w600)),
        const SizedBox(height: 6),
        for (final b in rows)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 3),
            child: Row(children: [
              SizedBox(width: 92, child: Text('${byAsset ? b['name'] : b['label']}', style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13))),
              SizedBox(width: 48, child: Text('${b['filled']}', style: numStyle.copyWith(color: p.muted, fontSize: 12.5))),
              SizedBox(width: 52, child: Text(_pct(b['win_rate']), style: numStyle.copyWith(fontSize: 12.5))),
              Expanded(child: Text(_r(b['avg_net_r']), style: numStyle.copyWith(fontSize: 12.5, color: _col(p, b['avg_net_r'])))),
              Text(_tr(b['total_net_r']), style: numStyle.copyWith(fontWeight: FontWeight.w700, fontSize: 12.5, color: _col(p, b['total_net_r']))),
            ]),
          ),
        Text('trades   win rate   avg net R   total', style: TextStyle(color: p.muted, fontSize: 10.5)),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final p = context.pal;
    final j = job;
    final status = '${j?['status'] ?? 'none'}';
    final running = status == 'running';
    final done = status == 'done';
    final overall = (j?['overall'] as Map?)?.cast<String, dynamic>();
    final prm = (j?['params'] as Map?)?.cast<String, dynamic>();
    return RefreshIndicator(
      onRefresh: _poll,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.all(12),
        children: [
          Panel(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('REPLAY THE STRATEGY ON HISTORY', style: TextStyle(color: p.muted, fontSize: 11, letterSpacing: 1, fontWeight: FontWeight.w600)),
              const SizedBox(height: 8),
              Wrap(spacing: 8, children: [
                for (final d in [30, 60, 90, 180])
                  ChoiceChip(label: Text('$d days'), selected: days == d, onSelected: running ? null : (_) => setState(() => days = d)),
              ]),
              const SizedBox(height: 8),
              SegmentedButton<String>(
                segments: [for (final e in styleLabels.entries) ButtonSegment(value: e.key, label: Text(e.value))],
                selected: {style},
                onSelectionChanged: running ? null : (s) => setState(() => style = s.first),
              ),
              const SizedBox(height: 8),
              Row(children: [
                Text('Fees per side:', style: TextStyle(color: p.muted, fontSize: 12.5)),
                const SizedBox(width: 8),
                Wrap(spacing: 8, children: [
                  for (final f in [0, 5, 10])
                    ChoiceChip(label: Text('$f bp'), selected: fee == f, onSelected: running ? null : (_) => setState(() => fee = f)),
                ]),
              ]),
              const SizedBox(height: 4),
              Text('plus 2 bp slippage per side. 5 bp is a typical Binance futures taker fee.', style: TextStyle(color: p.muted, fontSize: 11.5)),
              const SizedBox(height: 10),
              Row(children: [
                Expanded(
                  child: FilledButton.icon(
                    onPressed: (busy || running || !Api.ready) ? null : _start,
                    icon: const Icon(Icons.history, size: 18),
                    label: Text(running ? 'Running...' : 'Run backtest'),
                  ),
                ),
                if (running) ...[
                  const SizedBox(width: 8),
                  OutlinedButton(onPressed: _cancel, child: const Text('Cancel')),
                ],
              ]),
              const SizedBox(height: 6),
              Text(
                'Runs on the server in the background at low priority (several minutes for all 12 crypto assets). '
                'Crypto only: forex has no real volume data.',
                style: TextStyle(color: p.muted, fontSize: 11.5, height: 1.4),
              ),
            ]),
          ),
          if (err != null) Panel(child: Text(err!, style: TextStyle(color: p.loss))),
          if (running && j != null)
            Panel(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('Running: ${(j['progress'] as Map)['pct']}%  (${(j['progress'] as Map)['current'] ?? '-'}, '
                    '${(j['progress'] as Map)['done']}/${(j['progress'] as Map)['total']} assets)'),
                const SizedBox(height: 8),
                LinearProgressIndicator(value: ((j['progress'] as Map)['pct'] as num) / 100),
              ]),
            ),
          if (status == 'failed' || status == 'cancelled')
            Panel(child: Text('Last run: $status${j?['error'] != null ? ' (${j!['error']})' : ''}', style: TextStyle(color: p.warn))),
          if (done && overall != null && prm != null) ...[
            Panel(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('RESULT  -  ${styleLabels['${prm['style']}'] ?? prm['style']}, last ${prm['days']} days, ${(prm['assets'] as List).length} assets',
                    style: TextStyle(color: p.muted, fontSize: 11, letterSpacing: 1, fontWeight: FontWeight.w600)),
                const SizedBox(height: 10),
                _tier(p, 'All setups', (overall['all'] as Map?)?.cast<String, dynamic>()),
                _tier(p, 'Order block / FVG zones', (overall['ob_fvg'] as Map?)?.cast<String, dynamic>()),
                _tier(p, 'Order block + FVG + volume profile', (overall['ob_fvg_volume'] as Map?)?.cast<String, dynamic>()),
                Text('"Net" means after fees and slippage. R is your risk per trade: +1R = a win as big as the stop distance.',
                    style: TextStyle(color: p.muted, fontSize: 11.5)),
              ]),
            ),
            _rows(p, 'BY ASSET (BEST FIRST)', (j?['by_asset'] as List?) ?? [], byAsset: true),
            _rows(p, 'BY CONFIDENCE (SETUP QUALITY)', (overall['by_conf'] as List?) ?? []),
            _rows(p, 'BY ZONE TYPE', (overall['by_poi'] as List?) ?? []),
            _rows(p, 'BY DIRECTION', (overall['by_dir'] as List?) ?? []),
            Text(
              'How to read this: a strategy needs a profit factor above 1 and a positive average net R over a large number of trades. '
              'Fewer than about 30 trades in a row means the number is mostly noise. Same rules as the live journal: no look-ahead, '
              'stop wins if stop and TP1 share a candle, TP1 is the exit. News, funding and partial exits are not modelled, and '
              'past results do not predict future results.',
              style: TextStyle(color: p.muted, fontSize: 12, height: 1.4),
            ),
          ],
        ],
      ),
    );
  }
}
