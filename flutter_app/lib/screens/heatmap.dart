import 'package:flutter/material.dart';
import '../api.dart';
import '../prefs.dart';
import '../theme.dart';
import 'detail_sheet.dart';
import 'settings.dart' show styleLabels;

/// Bias of every asset on every timeframe at a glance, crypto and forex together.
class HeatmapView extends StatefulWidget {
  const HeatmapView({super.key});
  @override
  State<HeatmapView> createState() => _HeatmapViewState();
}

class _HeatmapViewState extends State<HeatmapView> with AutomaticKeepAliveClientMixin {
  String style = 'intraday';
  Map<String, dynamic>? data;
  bool loading = false;
  bool touched = false;
  String? err;
  int req = 0;
  int sortBy = -1; // -1 overall, -2 name, 0.. a timeframe column

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    _boot();
  }

  Future<void> _boot() async {
    if (!Api.ready) {
      setState(() => err = 'Enter your API token in Settings to connect.');
      return;
    }
    await ServerPrefs.I.load();
    final st = ServerPrefs.I.section('analyst')['style'];
    if (!touched && st is String && styleLabels.containsKey(st)) style = st;
    if (mounted) _load();
  }

  Future<void> _load() async {
    final my = ++req;
    setState(() {
      loading = true;
      err = null;
    });
    try {
      final d = await Api.get('/api/heatmap', {'style': style}) as Map<String, dynamic>;
      if (mounted && my == req) setState(() => data = d);
    } catch (e) {
      if (mounted && my == req) setState(() => err = '$e');
    }
    if (mounted && my == req) setState(() => loading = false);
  }

  Color _heat(Pal p, num? s) {
    if (s == null) return Color.lerp(p.surface, p.outline, 0.5)!;
    final t = (s.abs() / 70).clamp(0.0, 1.0).toDouble();
    return Color.lerp(p.surface, s >= 0 ? p.gain : p.loss, 0.15 + 0.75 * t)!;
  }

  String _sg(num v) => '${v > 0 ? '+' : ''}${v.toInt()}';

  List<Map<String, dynamic>> _sorted(List rows) {
    final r = rows.map((e) => e as Map<String, dynamic>).toList();
    num key(Map<String, dynamic> x) {
      if (sortBy == -1) return -(x['overall'] as num);
      final cells = (x['cells'] as List?) ?? [];
      if (sortBy >= 0 && sortBy < cells.length) {
        final sc = (cells[sortBy] as Map)['score'] as num?;
        return -(sc ?? -999);
      }
      return 0;
    }

    if (sortBy == -2) {
      r.sort((a, b) => '${a['name']}'.compareTo('${b['name']}'));
    } else {
      r.sort((a, b) => key(a).compareTo(key(b)));
    }
    return [...r.where((x) => x['open'] == true), ...r.where((x) => x['open'] != true)];
  }

  Widget _cell(Pal p, num? score, {double h = 30}) => Expanded(
        child: Container(
          height: h,
          margin: const EdgeInsets.all(1.5),
          alignment: Alignment.center,
          decoration: BoxDecoration(color: _heat(p, score), borderRadius: BorderRadius.circular(6)),
          child: Text(score == null ? '-' : _sg(score),
              style: const TextStyle(fontSize: 10.5, fontWeight: FontWeight.w700, color: Colors.white)),
        ),
      );

  Widget _header(Pal p, List<String> tfs) {
    Widget h(String t, int i) => Expanded(
          child: GestureDetector(
            onTap: () => setState(() => sortBy = i),
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 6),
              child: Center(
                child: Text(t,
                    style: TextStyle(fontSize: 11, fontWeight: sortBy == i ? FontWeight.w800 : FontWeight.w500, color: sortBy == i ? p.accent : p.muted)),
              ),
            ),
          ),
        );
    return Row(children: [
      SizedBox(
        width: 58,
        child: GestureDetector(
          onTap: () => setState(() => sortBy = -2),
          child: Text('Asset', style: TextStyle(fontSize: 11, color: sortBy == -2 ? p.accent : p.muted)),
        ),
      ),
      for (var i = 0; i < tfs.length; i++) h(tfs[i], i),
      SizedBox(
        width: 44,
        child: GestureDetector(
          onTap: () => setState(() => sortBy = -1),
          child: Text('All', textAlign: TextAlign.right, style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: sortBy == -1 ? p.accent : p.muted)),
        ),
      ),
    ]);
  }

  Widget _row(Pal p, Map<String, dynamic> r, VoidCallback onTap) {
    final open = r['open'] == true;
    final cells = (r['cells'] as List?) ?? [];
    final overall = (r['overall'] as num).toInt();
    final col = overall >= 20 ? p.gain : (overall <= -20 ? p.loss : p.muted);
    return InkWell(
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 1),
        child: Row(children: [
          SizedBox(width: 58, child: Text('${r['name']}', maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 12.5))),
          ...(open
              ? [for (final c in cells) _cell(p, (c as Map)['score'] as num?)]
              : [Expanded(child: Text('${r['market_status']}: no signals', style: TextStyle(color: p.muted, fontSize: 12)))]),
          SizedBox(
            width: 44,
            child: Text(open ? _sg(overall) : '', textAlign: TextAlign.right, style: numStyle.copyWith(fontWeight: FontWeight.w800, color: col)),
          ),
        ]),
      ),
    );
  }

  Widget _summary(Pal p, String title, Map<String, dynamic> s, List<String> tfs) {
    final bull = (s['bullish'] as num).toInt(), bear = (s['bearish'] as num).toInt(), neu = (s['neutral'] as num).toInt();
    final avg = (s['avg'] as num).toInt();
    final col = avg >= 10 ? p.gain : (avg <= -10 ? p.loss : p.muted);
    final tfAvg = (s['tf_avg'] as List?) ?? [];
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [
        Text(title, style: TextStyle(color: p.muted, fontSize: 11, letterSpacing: 1, fontWeight: FontWeight.w600)),
        const Spacer(),
        Text('${s['label']}', style: TextStyle(fontWeight: FontWeight.w800, fontSize: 16, color: col)),
        Text('  ${_sg(avg)}', style: numStyle.copyWith(color: col)),
      ]),
      const SizedBox(height: 6),
      if (bull + bear + neu > 0)
        ClipRRect(
          borderRadius: BorderRadius.circular(4),
          child: Row(children: [
            if (bull > 0) Expanded(flex: bull, child: Container(height: 8, color: p.gain)),
            if (neu > 0) Expanded(flex: neu, child: Container(height: 8, color: p.outline)),
            if (bear > 0) Expanded(flex: bear, child: Container(height: 8, color: p.loss)),
          ]),
        ),
      const SizedBox(height: 4),
      Text('$bull bullish  -  $neu neutral  -  $bear bearish' + ((s['closed'] as num) > 0 ? '  -  ${s['closed']} closed (no bias)' : ''),
          style: TextStyle(color: p.muted, fontSize: 12)),
      const SizedBox(height: 8),
      Row(children: [
        const SizedBox(width: 58, child: Text('All', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700))),
        for (final t in tfAvg) _cell(p, (t as Map)['avg'] as num?, h: 24),
        const SizedBox(width: 44),
      ]),
      const SizedBox(height: 4),
      _header(p, tfs),
    ]);
  }

  Widget _market(Pal p, String key, String title, List<String> tfs, String mstyle) {
    final m = (data!['markets'][key] as Map).cast<String, dynamic>();
    final rows = _sorted(m['rows'] as List);
    final items = rows.map((r) => {'name': '${r['name']}', 'label': '${r['label']}'}).toList();
    return Panel(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _summary(p, title, (m['summary'] as Map).cast<String, dynamic>(), tfs),
        for (var i = 0; i < rows.length; i++) _row(p, rows[i], () => showAnalysisSheet(context, items, i, mstyle)),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final p = context.pal;
    final d = data;
    final tfs = ((d?['tfs'] as List?) ?? []).map((e) => '$e').toList();
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.all(12),
        children: [
          SegmentedButton<String>(
            segments: [for (final e in styleLabels.entries) ButtonSegment(value: e.key, label: Text(e.value))],
            selected: {style},
            onSelectionChanged: (s) {
              touched = true;
              setState(() => style = s.first);
              _load();
            },
          ),
          const SizedBox(height: 6),
          Text('The last column weights the timeframes for the chosen style. Tap a header to sort, tap a row for the report.',
              style: TextStyle(color: p.muted, fontSize: 12)),
          const SizedBox(height: 6),
          if (loading) const LinearProgressIndicator(),
          if (err != null)
            Panel(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(err!, style: TextStyle(color: p.loss)),
                TextButton(onPressed: _boot, child: const Text('Retry')),
              ]),
            ),
          if (d != null) ...[
            _market(p, 'crypto', 'CRYPTO', tfs, '${d['style']}'),
            _market(p, 'forex', 'FOREX AND GOLD', tfs, '${d['style']}'),
          ],
          const SizedBox(height: 4),
          Text(
            'Each cell runs from -100 (bearish) to +100 (bullish) and combines the structure trend (HH+HL or LH+LL), '
            'a fresh break of structure and the RSI. Closed markets show no bias. Rule-based, not financial advice.',
            style: TextStyle(color: p.muted, fontSize: 12, height: 1.4),
          ),
        ],
      ),
    );
  }
}
