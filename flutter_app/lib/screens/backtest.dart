import 'dart:async';
import 'package:flutter/material.dart';
import '../api.dart';
import '../minichart.dart';
import '../theme.dart';
import 'settings.dart' show styleLabels;

const _ingredients = {
  'vp': 'Volume profile confluence',
  'volvalid': 'Volume validation',
  'trigger': 'Lower-timeframe confirmation',
  'sweep': 'Liquidity sweep',
  'loc': 'Discount / premium location',
  'rr': 'Reward-to-risk bonus',
  'htf': 'Against higher timeframes',
  'session': 'Kill zone',
  'range': 'Ranging higher timeframe',
};

/// Replays the analyst's setups on crypto history and tests them against a coin-flip baseline.
class BacktestView extends StatefulWidget {
  const BacktestView({super.key});
  @override
  State<BacktestView> createState() => _BacktestViewState();
}

class _BacktestViewState extends State<BacktestView> with AutomaticKeepAliveClientMixin {
  int days = 90;
  int offset = 0;
  String style = 'intraday';
  String mode = 'limit';
  int fee = 5;
  Map<String, dynamic>? job;
  Map<String, dynamic>? hyp;
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
      _loadHyp();
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
      final slim = await Api.get('/api/backtest/status', {'detail': '0'}) as Map<String, dynamic>;
      final have = job != null && job!['id'] == slim['id'] && job!['overall'] != null;
      Map<String, dynamic> j = slim;
      if (slim['status'] == 'done') {
        j = have ? job! : await Api.get('/api/backtest/status', {'detail': '1'}) as Map<String, dynamic>;
      }
      if (!mounted) return;
      setState(() {
        job = j;
        err = null;
      });
      final running = slim['status'] == 'running';
      if (slim['status'] == 'done' && (hyp == null || hypJob != slim['id'])) _loadHyp(slim['id'] as String?);
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

  String? hypJob;

  Future<void> _loadHyp([String? forJob]) async {
    try {
      final h = await Api.get('/api/hypotheses') as Map<String, dynamic>;
      if (mounted) {
        setState(() {
          hyp = h;
          hypJob = forJob ?? hypJob;
        });
      }
    } catch (_) {}
  }

  Future<void> _runHyp(Map<String, dynamic> run) async {
    setState(() {
      busy = true;
      err = null;
    });
    try {
      await Api.post('/api/backtest/start', {
        'days': run['days'],
        'offset_days': run['offset_days'],
        'style': run['style'],
        'fee_bp': run['fee_bp'],
        'slip_bp': run['slip_bp'],
        'min_conf': run['min_conf'],
        'rules': run['rules'],
      });
      job = null;
      await _poll();
    } catch (e) {
      if (mounted) setState(() => err = '$e');
    }
    if (mounted) setState(() => busy = false);
  }

  Widget _hypPanel(Pal p) {
    final hs = ((hyp?['hypotheses'] as List?) ?? []);
    if (hs.isEmpty) return const SizedBox.shrink();
    Color cc(String c) => c == 'pass' ? p.gain : (c == 'fail' ? p.loss : (c == 'open' ? p.warn : p.muted));
    return Panel(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('PRE-REGISTERED HYPOTHESES', style: TextStyle(color: p.muted, fontSize: 11, letterSpacing: 1, fontWeight: FontWeight.w600)),
        const SizedBox(height: 4),
        Text('Each was written down before the data that tests it. Only unseen (test) windows decide a verdict.',
            style: TextStyle(color: p.muted, fontSize: 11.5)),
        const SizedBox(height: 8),
        for (final raw in hs)
          Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('${raw['id']}  ${raw['title']}', style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 13.5)),
              const SizedBox(height: 2),
              Text('${raw['verdict']}', style: TextStyle(color: cc('${raw['cls']}'), fontWeight: FontWeight.w700, fontSize: 12.5)),
              for (final w in ((raw['windows'] as List?) ?? []))
                Text(
                  '${w['role'] == 'test' ? 'TEST' : 'seen'}  ${w['label']}: ' +
                      (w['missing'] == true
                          ? 'not run yet'
                          : (w['note'] != null
                              ? '${w['note']}'
                              : (raw['kind'] == 'diff'
                                  ? 'with bonus ${_r(w['avg_with'])} (${w['n_with']}) vs without ${_r(w['avg_without'])} (${w['n_without']})'
                                  : ((w['n'] as num) == 0
                                      ? 'no trades'
                                      : '${w['n']} trades, average ${_r(w['avg'])} (95%: ${(w['lo'] as num).toStringAsFixed(2)} to ${(w['hi'] as num).toStringAsFixed(2)})')))),
                  style: numStyle.copyWith(color: p.muted, fontSize: 11.5),
                ),
              if (raw['run'] != null)
                TextButton.icon(
                  onPressed: (busy || running) ? null : () => _runHyp((raw['run'] as Map).cast<String, dynamic>()),
                  icon: const Icon(Icons.play_arrow, size: 18),
                  label: Text('${(raw['run'] as Map)['label']}'),
                ),
            ]),
          ),
        Text('A confirmed hypothesis is evidence, not proof: it still needs a live journal that agrees.',
            style: TextStyle(color: p.muted, fontSize: 11.5)),
      ]),
    );
  }

  bool get running => job?['status'] == 'running';

  Future<void> _start() async {
    setState(() {
      busy = true;
      err = null;
    });
    try {
      await Api.post('/api/backtest/start',
          {'days': days, 'offset_days': offset, 'style': style, 'fee_bp': fee.toDouble(), 'slip_bp': 2.0, 'min_conf': 0});
      job = null;
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

  Widget _chip(Pal p, String text, Color c) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
        decoration: BoxDecoration(color: Color.lerp(p.surface, c, 0.22), borderRadius: BorderRadius.circular(6)),
        child: Text(text, style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w700, color: c)),
      );

  Widget _tier(Pal p, String title, Map<String, dynamic>? s) {
    if (s == null || (s['filled'] as num) == 0) {
      return Padding(
        padding: const EdgeInsets.only(bottom: 10),
        child: Text('$title: no filled setups', style: TextStyle(color: p.muted, fontSize: 12.5)),
      );
    }
    final pf = s['profit_factor'];
    final verdict = '${s['verdict']}';
    final vcol = verdict.startsWith('positive') ? p.gain : (verdict.startsWith('negative') ? p.loss : p.warn);
    final wci = s['win_ci'] as List?;
    final aci = s['avg_net_ci'] as List?;
    final base = (s['baseline'] as Map?)?.cast<String, dynamic>();
    final edge = s['edge'];
    final z = s['edge_z'];
    return Padding(
      padding: const EdgeInsets.only(bottom: 14),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text(title, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 13.5))),
          _chip(p, verdict.toUpperCase(), vcol),
        ]),
        const SizedBox(height: 4),
        Row(children: [
          _stat(p, _pct(s['win_rate']), 'win rate'),
          _stat(p, _r(s['avg_net_r']), 'avg net', color: _col(p, s['avg_net_r'])),
          _stat(p, _tr(s['total_net_r']), 'total net', color: _col(p, s['total_net_r'])),
          _stat(p, pf == null ? '-' : (pf as num).toStringAsFixed(2), 'profit factor'),
        ]),
        const SizedBox(height: 2),
        Text('${s['filled']} trades (${s['wins']} wins, ${s['losses']} stops)  -  max drawdown ${(s['max_dd_r'] as num).toStringAsFixed(1)}R${mode == 'limit' ? '  -  fill rate ${_pct(s['fill_rate'])}' : ''}',
            style: TextStyle(color: p.muted, fontSize: 11.5)),
        if (wci != null && aci != null)
          Text('95% range: win rate ${(wci[0] as num).toStringAsFixed(0)}-${(wci[1] as num).toStringAsFixed(0)}%, '
              'average ${(aci[0] as num).toStringAsFixed(2)} to ${(aci[1] as num).toStringAsFixed(2)}R',
              style: TextStyle(color: p.muted, fontSize: 11.5)),
        if (base != null)
          Text(
            'Coin flip on the same ${base['n']} filled trades (same stop and target, entered ${job?['baseline_basis'] == 'signal' ? 'when the setup appeared' : 'at the fill time'}): ${_r(base['avg_net_r'])} (${_pct(base['win_rate'])} wins).'
            '${edge != null ? '  Strategy vs coin flip: ${_r(edge)}${z != null ? ' (${(z as num).toStringAsFixed(1)} sigma)' : ''}' : ''}',
            style: TextStyle(color: p.muted, fontSize: 11.5),
          ),
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
              SizedBox(width: 118, child: Text('${byAsset ? b['name'] : b['label']}', style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 12.5))),
              SizedBox(width: 40, child: Text('${b['filled']}', style: numStyle.copyWith(color: p.muted, fontSize: 12.5))),
              SizedBox(width: 48, child: Text(_pct(b['win_rate']), style: numStyle.copyWith(fontSize: 12.5))),
              Expanded(child: Text(_r(b['avg_net_r']), style: numStyle.copyWith(fontSize: 12.5, color: _col(p, b['avg_net_r'])))),
              Text(_tr(b['total_net_r']), style: numStyle.copyWith(fontWeight: FontWeight.w700, fontSize: 12.5, color: _col(p, b['total_net_r']))),
            ]),
          ),
        Text('trades   win rate   avg net R   total', style: TextStyle(color: p.muted, fontSize: 10.5)),
      ]),
    );
  }

  Widget _distRows(Pal p, List items) {
    if (items.isEmpty) return const SizedBox.shrink();
    return Panel(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('FILL RATE BY DISTANCE TO THE ZONE WHEN THE SETUP APPEARS',
            style: TextStyle(color: p.muted, fontSize: 11, letterSpacing: 1, fontWeight: FontWeight.w600)),
        const SizedBox(height: 6),
        for (final b in items)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 3),
            child: Row(children: [
              SizedBox(width: 150, child: Text('${b['label']}', style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 12.5))),
              SizedBox(width: 60, child: Text('${b['logged']} set', style: numStyle.copyWith(color: p.muted, fontSize: 12))),
              SizedBox(width: 60, child: Text('${_pct(b['fill_rate'])} filled', style: numStyle.copyWith(fontSize: 12))),
              Expanded(child: Text(b['avg_net_r'] == null ? '' : _r(b['avg_net_r']), style: numStyle.copyWith(fontSize: 12, color: _col(p, b['avg_net_r'])))),
            ]),
          ),
        Text('Setups far from the zone rarely fill, so alerts for them are mostly noise.', style: TextStyle(color: p.muted, fontSize: 11.5)),
      ]),
    );
  }

  Widget _ablation(Pal p, List items) {
    if (items.isEmpty) return const SizedBox.shrink();
    return Panel(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('DOES EACH INGREDIENT HELP? (AVG NET R WITH vs WITHOUT)',
            style: TextStyle(color: p.muted, fontSize: 11, letterSpacing: 1, fontWeight: FontWeight.w600)),
        const SizedBox(height: 6),
        for (final b in items)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 3),
            child: Row(children: [
              Expanded(child: Text(_ingredients['${b['label']}'] ?? '${b['label']}', style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 12.5))),
              Text('${_r(b['avg_with'])} (${b['with']})', style: numStyle.copyWith(fontSize: 12, color: _col(p, b['avg_with']))),
              Text('  vs  ', style: TextStyle(color: p.muted, fontSize: 11)),
              Text('${_r(b['avg_without'])} (${b['without']})', style: numStyle.copyWith(fontSize: 12, color: _col(p, b['avg_without']))),
            ]),
          ),
        Text('Only ingredients with at least 15 trades on each side are listed. Differences smaller than about 0.2R are noise.',
            style: TextStyle(color: p.muted, fontSize: 11.5)),
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
    final ov = (j?[mode == 'confirm' ? 'overall_confirm' : 'overall'] as Map?)?.cast<String, dynamic>();
    final byAsset = (j?[mode == 'confirm' ? 'by_asset_confirm' : 'by_asset'] as List?) ?? [];
    final prm = (j?['params'] as Map?)?.cast<String, dynamic>();
    final equity = ((ov?['equity'] as List?) ?? []).map((e) => (e as num).toDouble()).toList();
    return RefreshIndicator(
      onRefresh: _poll,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.all(12),
        children: [
          _hypPanel(p),
          Panel(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('REPLAY THE STRATEGY ON HISTORY', style: TextStyle(color: p.muted, fontSize: 11, letterSpacing: 1, fontWeight: FontWeight.w600)),
              const SizedBox(height: 8),
              Wrap(spacing: 8, children: [
                for (final d in [30, 90, 180, 365])
                  ChoiceChip(label: Text('$d days'), selected: days == d, onSelected: running ? null : (_) => setState(() => days = d)),
              ]),
              const SizedBox(height: 6),
              Text('Period ends', style: TextStyle(color: p.muted, fontSize: 12.5)),
              Wrap(spacing: 8, children: [
                for (final o in [0, 90, 180, 365])
                  ChoiceChip(
                      label: Text(o == 0 ? 'now' : '$o d ago'),
                      selected: offset == o,
                      onSelected: running ? null : (_) => setState(() => offset = o)),
              ]),
              Padding(
                padding: const EdgeInsets.only(top: 2, bottom: 6),
                child: Text('An earlier period is data nobody has looked at yet: the honest test of a result you already saw.',
                    style: TextStyle(color: p.muted, fontSize: 11.5)),
              ),
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
                'Runs on the server in the background at low priority (several minutes; longer periods take longer and download '
                'more history the first time). Crypto only: forex has no real volume data.',
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
          if (done && ov != null && prm != null) ...[
            SegmentedButton<String>(
              segments: const [
                ButtonSegment(value: 'limit', label: Text('Blind limit')),
                ButtonSegment(value: 'confirm', label: Text('Confirmed entry')),
              ],
              selected: {mode},
              onSelectionChanged: (s) => setState(() => mode = s.first),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(2, 6, 2, 6),
              child: Text(
                mode == 'limit'
                    ? 'Blind limit: a resting order at the zone midpoint that fills on touch, whatever the price does next.'
                    : 'Confirmed entry: wait until price is inside the zone and a 5-minute CHoCH or BOS in the trade direction appears, then enter at its close (stop beyond the zone, same TP1).',
                style: TextStyle(color: p.muted, fontSize: 12, height: 1.35),
              ),
            ),
            Panel(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(
                    'RESULT  -  ${styleLabels['${prm['style']}'] ?? prm['style']}, ${prm['days']} days'
                    '${(prm['offset_days'] as num?) != null && (prm['offset_days'] as num) > 0 ? ', ended ${prm['offset_days']} d ago' : ''}, ${(prm['assets'] as List).length} assets${prm['rules'] != null ? '  -  rules ${prm['rules']}' : ''}',
                    style: TextStyle(color: p.muted, fontSize: 11, letterSpacing: 1, fontWeight: FontWeight.w600)),
                const SizedBox(height: 10),
                _tier(p, 'All setups', (ov['all'] as Map?)?.cast<String, dynamic>()),
                _tier(p, 'Order block / FVG zones', (ov['ob_fvg'] as Map?)?.cast<String, dynamic>()),
                _tier(p, 'Order block + FVG + volume profile', (ov['ob_fvg_volume'] as Map?)?.cast<String, dynamic>()),
                if (equity.length > 3) ...[
                  Text('Cumulative net R over time', style: TextStyle(color: p.muted, fontSize: 11.5)),
                  const SizedBox(height: 4),
                  Sparkline(values: equity, color: equity.last >= 0 ? p.gain : p.loss, width: 300, height: 50),
                  const SizedBox(height: 8),
                ],
                Text('"Net" means after fees and slippage. R is your risk per trade: +1R = a win as big as the stop distance. '
                    'At 1% risk per trade, ${(((ov['all'] as Map)['total_net_r'] as num) * 1).toStringAsFixed(0)}R would be about '
                    '${(((ov['all'] as Map)['total_net_r'] as num) * 1).toStringAsFixed(0)}% of equity.',
                    style: TextStyle(color: p.muted, fontSize: 11.5)),
              ]),
            ),
            _rows(p, 'BY ASSET (BEST FIRST)', byAsset, byAsset: true),
            _rows(p, 'BY CONFIDENCE (SETUP QUALITY)', (ov['by_conf'] as List?) ?? []),
            if (mode == 'limit') _distRows(p, (ov['by_dist'] as List?) ?? []),
            _ablation(p, (ov['ablation'] as List?) ?? []),
            _rows(p, 'BY TIME (STABLE OVER TIME?)', (ov['by_third'] as List?) ?? []),
            _rows(p, 'BY ZONE TYPE', (ov['by_poi'] as List?) ?? []),
            _rows(p, 'BY DIRECTION', (ov['by_dir'] as List?) ?? []),
            Text(
              'How to read this: "positive (significant)" means the 95% range for the average net R is above zero; anything else '
              'is not proof. Compare with the coin-flip line: a strategy that does not beat entering at random with the same risk '
              'has no edge. Assets are correlated, so 12 assets are not 12 independent tests. Same rules as the live journal: no '
              'look-ahead, TP1 is the exit, the stop wins if stop and TP1 share a candle. News, funding and partial exits are not '
              'modelled. Past results do not predict future results.',
              style: TextStyle(color: p.muted, fontSize: 12, height: 1.4),
            ),
          ],
        ],
      ),
    );
  }
}
