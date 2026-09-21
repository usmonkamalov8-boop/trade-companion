import 'dart:async';
import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';
import '../api.dart';
import '../prefs.dart';
import '../theme.dart';
import 'settings.dart' show styleLabels;

class MarketsPage extends StatelessWidget {
  const MarketsPage({super.key});
  @override
  Widget build(BuildContext context) => DefaultTabController(
        length: 6,
        child: Scaffold(
          appBar: AppBar(
            title: const Text('Markets'),
            bottom: const TabBar(isScrollable: true, tabs: [
              Tab(text: 'Crypto'),
              Tab(text: 'Forex and gold'),
              Tab(text: 'Screener'),
              Tab(text: 'Journal'),
              Tab(text: 'Calendar'),
              Tab(text: 'News'),
            ]),
          ),
          body: const TabBarView(children: [
            MarketView('crypto'),
            MarketView('forex'),
            SetupsView(),
            JournalView(),
            CalendarView(),
            NewsView(),
          ]),
        ),
      );
}

class MarketView extends StatefulWidget {
  final String market;
  const MarketView(this.market, {super.key});
  @override
  State<MarketView> createState() => _MarketViewState();
}

class _MarketViewState extends State<MarketView> with AutomaticKeepAliveClientMixin {
  List rows = [];
  String text = '';
  bool busy = false;
  String? err;

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    if (Api.ready) _reload();
  }

  Future<void> _reload() async {
    if (!Api.ready) {
      setState(() => err = 'Enter your API token in Settings to connect.');
      return;
    }
    setState(() {
      busy = true;
      text = '';
      err = null;
    });
    try {
      final d = await Api.get('/api/scanner', {'market': widget.market});
      if (mounted) setState(() => rows = d as List);
    } catch (e) {
      if (mounted) setState(() => err = '$e');
    }
    try {
      await for (final c in Api.stream('/api/insights/stream', q: {'market': widget.market})) {
        if (!mounted) return;
        setState(() => text += c);
      }
    } catch (e) {
      if (mounted) setState(() => err = '$e');
    }
    if (mounted) setState(() => busy = false);
  }

  Widget _tfTag(Pal p, String k, int score) => Container(
        margin: const EdgeInsets.only(left: 4),
        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(6),
          border: Border.all(color: biasColor(p, score)),
        ),
        child: Text(k.toUpperCase(), style: TextStyle(fontSize: 11, color: biasColor(p, score))),
      );

  Widget _row(Pal p, Map<String, dynamic> r) {
    final score = (r['score'] as num).toInt();
    final chg = (r['change_pct'] as num).toDouble();
    final tf = r['tf'] as Map<String, dynamic>;
    return Panel(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text('${r['label']}', style: const TextStyle(fontWeight: FontWeight.w700))),
          Text('${r['status'] ?? ''}   ', style: TextStyle(fontSize: 11, color: r['open'] == false ? p.loss : p.gain)),
          Text('${r['price_str']}', style: numStyle.copyWith(fontWeight: FontWeight.w600)),
        ]),
        const SizedBox(height: 4),
        if (r['open'] == false)
          Text('MARKET CLOSED (WEEKEND): no signals, last close shown', style: TextStyle(color: p.loss, fontWeight: FontWeight.w600, fontSize: 12.5))
        else
        Row(children: [
          Text('${r['bias']} (${signed(score, 0)})',
              style: TextStyle(color: biasColor(p, score), fontWeight: FontWeight.w600)),
          const SizedBox(width: 10),
          Text('${signed(chg)}%', style: numStyle.copyWith(color: chg >= 0 ? p.gain : p.loss)),
          const Spacer(),
          for (final k in ['1h', '4h', '1d'])
            if (tf[k] != null) _tfTag(p, k, (tf[k]['score'] as num).toInt()),
        ]),
        if (r['open'] != false) ...[
          const SizedBox(height: 4),
          Text('RSI ${r['rsi'] ?? '-'}   support ${r['support_str']}   resistance ${r['resistance_str']}',
              style: numStyle.copyWith(color: p.muted, fontSize: 12)),
        ],
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final p = context.pal;
    return RefreshIndicator(
      onRefresh: _reload,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.all(12),
        children: [
          if (busy) const LinearProgressIndicator(),
          if (err != null) Panel(child: Text(err!, style: TextStyle(color: p.loss))),
          for (final r in rows) _row(p, r as Map<String, dynamic>),
          if (text.isNotEmpty) const Heading('Briefing'),
          if (text.isNotEmpty) Panel(child: SelectableText(text, style: const TextStyle(height: 1.4))),
          const SizedBox(height: 12),
          Text('Pull down to refresh. Colored tags show 1H, 4H and 1D trend.',
              style: TextStyle(color: p.muted, fontSize: 12)),
        ],
      ),
    );
  }
}

class NewsView extends StatefulWidget {
  const NewsView({super.key});
  @override
  State<NewsView> createState() => _NewsViewState();
}

class _NewsViewState extends State<NewsView> with AutomaticKeepAliveClientMixin {
  String cat = 'crypto';
  List items = [];
  String? err;
  bool loading = false;

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    if (Api.ready) _load();
  }

  Future<void> _load() async {
    setState(() {
      loading = true;
      err = null;
    });
    try {
      final d = await Api.get('/api/news', {'category': cat});
      if (mounted) setState(() => items = d as List);
    } catch (e) {
      if (mounted) setState(() => err = '$e');
    }
    if (mounted) setState(() => loading = false);
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final p = context.pal;
    return Column(children: [
      Padding(
        padding: const EdgeInsets.all(10),
        child: SegmentedButton<String>(
          segments: const [
            ButtonSegment(value: 'crypto', label: Text('Crypto')),
            ButtonSegment(value: 'forex', label: Text('Forex and gold')),
          ],
          selected: {cat},
          onSelectionChanged: (s) {
            setState(() => cat = s.first);
            _load();
          },
        ),
      ),
      if (loading) const LinearProgressIndicator(),
      Expanded(
        child: RefreshIndicator(
          onRefresh: _load,
          child: ListView.separated(
            physics: const AlwaysScrollableScrollPhysics(),
            itemCount: items.isEmpty ? 1 : items.length,
            separatorBuilder: (_, __) => Divider(height: 1, color: p.outline),
            itemBuilder: (_, i) {
              if (items.isEmpty) {
                return Padding(
                  padding: const EdgeInsets.all(16),
                  child: Text(err ?? (loading ? '' : 'No headlines yet. Pull down to refresh.'),
                      style: TextStyle(color: err != null ? p.loss : p.muted)),
                );
              }
              final n = items[i] as Map<String, dynamic>;
              final sent = (n['sent'] as num).toInt();
              return ListTile(
                leading: Icon(
                  sent > 0 ? Icons.arrow_upward : (sent < 0 ? Icons.arrow_downward : Icons.remove),
                  color: sent > 0 ? p.gain : (sent < 0 ? p.loss : p.muted),
                  size: 20,
                ),
                title: Text('${n['title']}', style: const TextStyle(fontSize: 14.5)),
                subtitle: Text('${n['source']}', style: TextStyle(color: p.muted, fontSize: 12)),
                onTap: () => launchUrl(Uri.parse('${n['link']}'), mode: LaunchMode.externalApplication),
              );
            },
          ),
        ),
      ),
    ]);
  }
}

// ----------------------------------------------------------------- screener

class SetupsView extends StatefulWidget {
  const SetupsView({super.key});
  @override
  State<SetupsView> createState() => _SetupsViewState();
}

class _SetupsViewState extends State<SetupsView> with AutomaticKeepAliveClientMixin {
  String market = 'crypto';
  String style = 'intraday';
  String view = 'list';
  String filter = 'all';
  List rows = [];
  Map<String, dynamic> summary = {};
  Map<String, dynamic> mstatus = {};
  bool loading = false;
  bool touched = false;
  String? err;
  int req = 0;

  static const filters = {
    'all': 'All',
    'open': 'Open',
    'bullish': 'Bullish',
    'bearish': 'Bearish',
    'zone': 'In zone',
    'ready': 'Ready',
  };

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
      final d = await Api.get('/api/screener', {'market': market, 'style': style}) as Map<String, dynamic>;
      if (mounted && my == req) {
        setState(() {
          rows = d['rows'] as List;
          summary = (d['summary'] as Map?)?.cast<String, dynamic>() ?? {};
          mstatus = (d['market_status'] as Map?)?.cast<String, dynamic>() ?? {};
        });
      }
    } catch (e) {
      if (mounted && my == req) setState(() => err = '$e');
    }
    if (mounted && my == req) setState(() => loading = false);
  }

  List get visible {
    bool keep(Map<String, dynamic> r) {
      final z = (r['zones'] as Map?) ?? {};
      switch (filter) {
        case 'open':
          return r['open'] == true;
        case 'bullish':
          return r['bias'] == 'Bullish';
        case 'bearish':
          return r['bias'] == 'Bearish';
        case 'zone':
          return z['in_zone'] == true;
        case 'ready':
          return r['status'] == 'READY';
      }
      return true;
    }

    return rows.where((r) => keep(r as Map<String, dynamic>)).toList();
  }

  Widget _chip(Pal p, String text, Color c) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
        margin: const EdgeInsets.only(right: 6),
        decoration: BoxDecoration(color: Color.lerp(p.surface, c, 0.22), borderRadius: BorderRadius.circular(6)),
        child: Text(text, style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w700, color: c)),
      );

  Color _statusColor(Pal p, String s) =>
      s == 'READY' ? p.gain : (s == 'IN ZONE' ? p.warn : (s == 'NEWS HOLD' || s == 'MARKET CLOSED' ? p.loss : p.muted));

  Color _biasColor(Pal p, String b) => b == 'Bullish' ? p.gain : (b == 'Bearish' ? p.loss : p.muted);

  String _biasArrow(String b) => b == 'Bullish' ? '\u25B2' : (b == 'Bearish' ? '\u25BC' : '\u2013');

  /// One compact screener row: open/closed, bias, active zones, setup status.
  Widget _srow(Pal p, Map<String, dynamic> r, int index) {
    final open = r['open'] == true;
    final z = (r['zones'] as Map?)?.cast<String, dynamic>() ?? {};
    final bias = '${r['bias']}';
    final dir = '${r['direction']}';
    final vp = r['vp'] as Map<String, dynamic>?;
    final nearest = z['nearest'];
    return Panel(
      child: InkWell(
        onTap: () => _detail(index),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(
              child: Text('${r['name']}  ${r['label']}', style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15)),
            ),
            Text('${r['price_str']}', style: numStyle.copyWith(color: p.muted)),
          ]),
          const SizedBox(height: 6),
          Wrap(runSpacing: 4, children: [
            _chip(p, open ? '\u25CF ${r['market_status']}' : '\u25CB ${r['market_status']}', open ? p.gain : p.loss),
            if (open) _chip(p, '${_biasArrow(bias)} $bias ${(r['bias_pct'] as num) >= 0 ? '+' : ''}${r['bias_pct']}%', _biasColor(p, bias)),
            if (open) _chip(p, 'Zones ${z['count'] ?? 0}${z['in_zone'] == true ? '  IN ZONE' : ''}', z['in_zone'] == true ? p.warn : p.muted),
            if (open && dir != 'none') _chip(p, '${dir.toUpperCase()} ${r['status']} ${r['confidence']}', _statusColor(p, '${r['status']}')),
            if (open && dir == 'none') _chip(p, '${r['status']}', p.muted),
            if (!open) _chip(p, '${r['status']}', p.muted),
          ]),
          if (open && nearest != null)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text('Nearest: $nearest', style: numStyle.copyWith(color: p.muted, fontSize: 11.5)),
            ),
          if (open && vp != null)
            Padding(
              padding: const EdgeInsets.only(top: 2),
              child: Text('Volume ${vp['tf']}: POC ${vp['poc']}  VA ${vp['val']} - ${vp['vah']}  (price ${vp['pos']})',
                  style: numStyle.copyWith(color: p.muted, fontSize: 11.5)),
            ),
          if (!open && r['reopen'] != null)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text('Reopens ${r['reopen']}. No signals while closed.', style: TextStyle(color: p.muted, fontSize: 12)),
            ),
        ]),
      ),
    );
  }

  Widget _banner(Pal p) {
    if (mstatus.isEmpty) return const SizedBox.shrink();
    final open = mstatus['open'] == true;
    final col = open ? p.gain : p.loss;
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: p.surface,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: open ? p.outline : col, width: open ? 1 : 1.6),
      ),
      child: Row(children: [
        Icon(open ? Icons.lock_open : Icons.lock_outline, color: col, size: 20),
        const SizedBox(width: 10),
        Expanded(child: Text('${mstatus['text']}', style: TextStyle(color: open ? p.muted : col, fontSize: 13, fontWeight: FontWeight.w600))),
      ]),
    );
  }

  Widget _summaryLine(Pal p) {
    if (summary.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Text(
        '${summary['open']} open  -  ${summary['bullish']} bullish  -  ${summary['bearish']} bearish  -  '
        '${summary['in_zone']} in a zone  -  ${summary['ready']} ready',
        style: TextStyle(color: p.muted, fontSize: 12),
      ),
    );
  }

  Widget _closedCard(Pal p, Map<String, dynamic> r, int index) {
    final notes = (r['notes'] as List?) ?? [];
    return Panel(
      child: InkWell(
        onTap: () => _detail(index),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(child: Text('${r['name']}  ${r['label']}', style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15.5))),
            Text('${r['price_str']}', style: numStyle.copyWith(color: p.muted)),
          ]),
          const SizedBox(height: 6),
          _chip(p, '${r['status']}'.toUpperCase(), p.loss),
          for (final n in notes) Text('$n', style: TextStyle(color: p.muted, fontSize: 12.5, height: 1.4)),
        ]),
      ),
    );
  }

  Widget _card(Pal p, Map<String, dynamic> r, int index) {
    if (r['open'] == false) return _closedCard(p, r, index);
    final dir = '${r['direction']}';
    final none = dir == 'none';
    final col = none ? p.muted : (dir == 'long' ? p.gain : p.loss);
    final conf = (r['confidence'] as num).toInt();
    final cc = conf >= 70 ? p.gain : (conf >= 50 ? p.warn : p.muted);
    final hasPoi = r['poi'] != null;
    final tfs = (r['tf'] as List?) ?? [];
    final notes = (r['notes'] as List?) ?? [];
    final conflu = ((r['confluence'] as List?) ?? []).join(', ');
    return Panel(
      child: InkWell(
        onTap: () => _detail(index),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(
              child: Text('${r['name']}  ${r['label']}', style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15.5)),
            ),
            Text('${r['price_str']}', style: numStyle.copyWith(color: p.muted)),
          ]),
          const SizedBox(height: 6),
          Row(children: [
            _chip(p, none ? 'NO TRADE' : dir.toUpperCase(), col),
            _chip(p, '${r['status']}', _statusColor(p, '${r['status']}')),
            const Spacer(),
            Text('${r['confidence']}', style: numStyle.copyWith(color: cc, fontWeight: FontWeight.w800, fontSize: 16)),
            Text(' ${r['conf_label']}', style: TextStyle(color: cc, fontSize: 12)),
          ]),
          const SizedBox(height: 6),
          LinearProgressIndicator(
            value: conf / 100,
            minHeight: 4,
            color: cc,
            backgroundColor: p.outline,
            borderRadius: BorderRadius.circular(2),
          ),
          const SizedBox(height: 8),
          if (hasPoi) ...[
            Text('POI  ${r['poi']}${conflu.isEmpty ? '' : '  (+ $conflu)'}', style: numStyle.copyWith(fontSize: 12.5)),
            Text('Entry ${r['entry']}   Stop ${r['stop']}', style: numStyle.copyWith(fontSize: 12.5)),
            Text('TP1 ${r['tp1']} (${r['rr1']}R)   TP2 ${r['tp2']} (${r['rr2']}R)', style: numStyle.copyWith(fontSize: 12.5)),
          ] else if (notes.isNotEmpty)
            Text('${notes.first}', style: TextStyle(color: p.muted, fontSize: 12.5)),
          if (r['refine'] != null)
            Padding(
              padding: const EdgeInsets.only(top: 2),
              child: Text('Micro entry: ${r['refine']}', style: numStyle.copyWith(fontSize: 12.5, color: p.accent)),
            ),
          if (r['news'] != null)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Text(
                '${(r['news'] as Map)['hold'] == true ? 'NEWS HOLD: ' : 'News: '}${(r['news'] as Map)['line']} (${(r['news'] as Map)['pts']} confidence)',
                style: TextStyle(color: p.warn, fontSize: 12.5, fontWeight: FontWeight.w700),
              ),
            ),
          const SizedBox(height: 8),
          Text('STRUCTURE BY TIMEFRAME  (BOS / CHoCH / OB / FVG)',
              style: TextStyle(color: p.muted, fontSize: 10.5, letterSpacing: 0.6, fontWeight: FontWeight.w600)),
          const SizedBox(height: 4),
          for (final t in tfs) _tfRow(p, t as Map<String, dynamic>),
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton.icon(
              onPressed: () => _detail(index, focus: 'xray'),
              icon: const Icon(Icons.troubleshoot, size: 18),
              label: const Text('Why this score? (Trade X-Ray)'),
            ),
          ),
        ]),
      ),
    );
  }

  Widget _tfRow(Pal p, Map<String, dynamic> t) {
    final trend = (t['trend'] as num).toInt();
    final col = trend == 1 ? p.gain : (trend == -1 ? p.loss : p.muted);
    final arrow = trend == 1 ? '\u25B2' : (trend == -1 ? '\u25BC' : '\u2013');
    Color dc(dynamic d) => (d as num).toInt() == 1 ? p.gain : p.loss;
    String ar(dynamic d) => (d as num).toInt() == 1 ? '\u2191' : '\u2193';
    final bos = t['bos'] as Map<String, dynamic>?;
    final choch = t['choch'] as Map<String, dynamic>?;
    final ob = (t['ob'] as List?) ?? [];
    final fvg = (t['fvg'] as List?) ?? [];
    final role = '${t['role'] ?? ''}';
    final spans = <InlineSpan>[];
    if (bos != null) {
      spans.add(TextSpan(text: 'BOS${ar(bos['dir'])} ${bos['ago']}b', style: TextStyle(color: dc(bos['dir']))));
    }
    if (choch != null) {
      if (spans.isNotEmpty) spans.add(const TextSpan(text: '   '));
      spans.add(TextSpan(text: 'CHoCH${ar(choch['dir'])} ${choch['ago']}b', style: TextStyle(color: dc(choch['dir']))));
    }
    if (spans.isEmpty) spans.add(TextSpan(text: 'no structure break', style: TextStyle(color: p.muted)));
    final zones = <InlineSpan>[];
    if (ob.isNotEmpty) {
      final z = ob.first as Map<String, dynamic>;
      zones.add(TextSpan(text: 'OB ${z['dir'] == 1 ? '\u25B2' : '\u25BC'} ${z['zone']}', style: TextStyle(color: dc(z['dir']))));
    }
    if (fvg.isNotEmpty) {
      final z = fvg.first as Map<String, dynamic>;
      if (zones.isNotEmpty) zones.add(const TextSpan(text: '   '));
      zones.add(TextSpan(text: 'FVG ${z['dir'] == 1 ? '\u25B2' : '\u25BC'} ${z['zone']}', style: TextStyle(color: dc(z['dir']))));
    }
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        SizedBox(width: 38, child: Text('${t['tf']}', style: TextStyle(fontWeight: FontWeight.w800, fontSize: 12.5, color: col))),
        SizedBox(width: 16, child: Text(arrow, style: TextStyle(fontSize: 11, color: col))),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text.rich(TextSpan(children: spans), style: numStyle.copyWith(fontSize: 12, fontWeight: FontWeight.w600)),
            if (zones.isNotEmpty) Text.rich(TextSpan(children: zones), style: numStyle.copyWith(fontSize: 11.5)),
          ]),
        ),
        if (role.isNotEmpty) Text(role, style: TextStyle(color: p.muted, fontSize: 10.5)),
      ]),
    );
  }

  void _detail(int index, {String focus = ''}) {
    final p = context.pal;
    final list = visible.map((r) => {'name': '${(r as Map)['name']}', 'label': '${r['label']}'}).toList();
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: p.surface,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(16))),
      builder: (_) => FractionallySizedBox(
        heightFactor: 0.92,
        child: _DetailSheet(items: list, start: index, style: style, initialFocus: focus),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final p = context.pal;
    final list = visible;
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.all(12),
        children: [
          SegmentedButton<String>(
            segments: const [
              ButtonSegment(value: 'crypto', label: Text('Crypto')),
              ButtonSegment(value: 'forex', label: Text('Forex and gold')),
            ],
            selected: {market},
            onSelectionChanged: (s) {
              setState(() {
                market = s.first;
                rows = [];
                summary = {};
                mstatus = {};
              });
              _load();
            },
          ),
          const SizedBox(height: 8),
          SegmentedButton<String>(
            segments: [for (final e in styleLabels.entries) ButtonSegment(value: e.key, label: Text(e.value))],
            selected: {style},
            onSelectionChanged: (s) {
              touched = true;
              setState(() {
                style = s.first;
                rows = [];
              });
              _load();
            },
          ),
          const SizedBox(height: 8),
          SegmentedButton<String>(
            segments: const [
              ButtonSegment(value: 'list', label: Text('Screener'), icon: Icon(Icons.view_list, size: 18)),
              ButtonSegment(value: 'cards', label: Text('Detailed cards'), icon: Icon(Icons.view_agenda_outlined, size: 18)),
            ],
            selected: {view},
            onSelectionChanged: (s) => setState(() => view = s.first),
          ),
          const SizedBox(height: 8),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Row(children: [
              for (final e in filters.entries)
                Padding(
                  padding: const EdgeInsets.only(right: 6),
                  child: ChoiceChip(
                    label: Text(e.value),
                    selected: filter == e.key,
                    onSelected: (_) => setState(() => filter = e.key),
                  ),
                ),
            ]),
          ),
          const SizedBox(height: 8),
          _banner(p),
          _summaryLine(p),
          if (loading) const LinearProgressIndicator(),
          if (err != null)
            Panel(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(err!, style: TextStyle(color: p.loss)),
                TextButton(onPressed: _boot, child: const Text('Retry')),
              ]),
            ),
          if (rows.isEmpty && !loading && err == null)
            Padding(
              padding: const EdgeInsets.all(24),
              child: Text('No data yet. Pull down to refresh.', textAlign: TextAlign.center, style: TextStyle(color: p.muted)),
            ),
          if (rows.isNotEmpty && list.isEmpty)
            Padding(
              padding: const EdgeInsets.all(20),
              child: Text('Nothing matches this filter.', textAlign: TextAlign.center, style: TextStyle(color: p.muted)),
            ),
          for (var i = 0; i < list.length; i++)
            view == 'list' ? _srow(p, list[i] as Map<String, dynamic>, i) : _card(p, list[i] as Map<String, dynamic>, i),
          const SizedBox(height: 8),
          Text(
            'Tap an asset for the full multi-timeframe report and use the arrows to move to the next one. '
            'Rule-based analysis, not financial advice.',
            style: TextStyle(color: p.muted, fontSize: 12, height: 1.4),
          ),
        ],
      ),
    );
  }
}

class _DetailSheet extends StatefulWidget {
  final List<Map<String, String>> items;
  final int start;
  final String style, initialFocus;
  const _DetailSheet({required this.items, required this.start, required this.style, this.initialFocus = ''});
  @override
  State<_DetailSheet> createState() => _DetailSheetState();
}

class _DetailSheetState extends State<_DetailSheet> {
  static const focuses = {
    '': 'Full report',
    'xray': 'Trade X-Ray',
    'topdown': 'Top-down (all TFs)',
    'structure': 'BOS / CHoCH',
    'ob': 'Order blocks',
    'fvg': 'Fair value gaps',
    'sd': 'Supply / demand',
    'sr': 'Support / resistance',
    'fib': 'Fibonacci',
    'trend': 'Trendlines',
    'liquidity': 'Liquidity',
    'volume': 'Volume profile',
    'ict': 'ICT',
    'poi': 'POI and setup',
  };
  String focus = '';
  int idx = 0;
  String? text;
  String? err;
  int req = 0;

  @override
  void initState() {
    super.initState();
    focus = widget.initialFocus;
    idx = widget.start.clamp(0, widget.items.length - 1).toInt();
    _load();
  }

  Future<void> _load() async {
    final my = ++req;
    setState(() {
      text = null;
      err = null;
    });
    try {
      final d = await Api.get('/api/analysis', {'name': widget.items[idx]['name']!, 'style': widget.style, if (focus.isNotEmpty) 'focus': focus})
          as Map<String, dynamic>;
      if (mounted && my == req) setState(() => text = '${d['text']}');
    } catch (e) {
      if (mounted && my == req) setState(() => err = '$e');
    }
  }

  void _go(int d) {
    idx = (idx + d).clamp(0, widget.items.length - 1).toInt();
    _load();
  }

  @override
  Widget build(BuildContext context) {
    final p = context.pal;
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          IconButton(onPressed: idx > 0 ? () => _go(-1) : null, icon: const Icon(Icons.chevron_left)),
          Expanded(
            child: Text(
              '${widget.items[idx]['name']}  ${widget.items[idx]['label']}  -  ${styleLabels[widget.style] ?? ''}   (${idx + 1}/${widget.items.length})',
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15),
            ),
          ),
          IconButton(onPressed: idx < widget.items.length - 1 ? () => _go(1) : null, icon: const Icon(Icons.chevron_right)),
          IconButton(onPressed: () => Navigator.of(context).pop(), icon: const Icon(Icons.close)),
        ]),
        SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: Row(children: [
            for (final e in focuses.entries)
              Padding(
                padding: const EdgeInsets.only(right: 6),
                child: ChoiceChip(
                  label: Text(e.value),
                  selected: focus == e.key,
                  onSelected: (_) {
                    focus = e.key;
                    _load();
                  },
                ),
              ),
          ]),
        ),
        const SizedBox(height: 8),
        Expanded(
          child: err != null
              ? Text(err!, style: TextStyle(color: p.loss))
              : (text == null
                  ? const Center(child: CircularProgressIndicator())
                  : SingleChildScrollView(
                      child: SelectableText(text!, style: numStyle.copyWith(fontSize: 12.8, height: 1.5)),
                    )),
        ),
      ]),
    );
  }
}

// ------------------------------------------------------------------ journal

class JournalView extends StatefulWidget {
  const JournalView({super.key});
  @override
  State<JournalView> createState() => _JournalViewState();
}

class _JournalViewState extends State<JournalView> with AutomaticKeepAliveClientMixin {
  String style = '';
  String scope = '';
  Map<String, dynamic>? stats;
  List items = [];
  bool loading = false;
  String? err;
  int req = 0;

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    if (Api.ready) {
      _load();
    } else {
      err = 'Enter your API token in Settings to connect.';
    }
  }

  Future<void> _load() async {
    final my = ++req;
    setState(() {
      loading = true;
      err = null;
    });
    try {
      final s = await Api.get('/api/journal/stats', {'days': '90', if (style.isNotEmpty) 'style': style}) as Map<String, dynamic>;
      final l = await Api.get('/api/journal', {
        'limit': '60',
        if (style.isNotEmpty) 'style': style,
        if (scope.isNotEmpty) 'state': scope,
      }) as Map<String, dynamic>;
      if (mounted && my == req) {
        setState(() {
          stats = s;
          items = l['items'] as List;
        });
      }
    } catch (e) {
      if (mounted && my == req) setState(() => err = '$e');
    }
    if (mounted && my == req) setState(() => loading = false);
  }

  String _pct(dynamic v) => v == null ? '-' : '${(v as num).toStringAsFixed(0)}%';
  String _r(dynamic v) => v == null ? '-' : '${(v as num) >= 0 ? '+' : ''}${(v as num).toStringAsFixed(2)}R';

  String _ago(num ts) {
    final m = ((DateTime.now().millisecondsSinceEpoch / 1000 - ts) / 60).round();
    if (m < 60) return '${m < 1 ? 1 : m} min ago';
    if (m < 1440) return '${m ~/ 60} h ago';
    return '${m ~/ 1440} d ago';
  }

  (String, Color) _outcome(Pal p, Map<String, dynamic> e) {
    final res = e['result'];
    switch (res) {
      case 'win':
        return ('TP1 HIT', p.gain);
      case 'loss':
        return ('STOPPED', p.loss);
      case 'timeout':
        return ('TIMED OUT', p.muted);
      case 'missed':
        return ('MISSED', p.muted);
      case 'expired':
        return ('EXPIRED', p.muted);
      case 'invalid':
        return ('INVALID', p.muted);
      case 'superseded':
        return ('REPLACED', p.muted);
    }
    return e['state'] == 'active' ? ('OPEN', p.warn) : ('WAITING', p.muted);
  }

  Widget _chip(Pal p, String text, Color c) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
        decoration: BoxDecoration(color: Color.lerp(p.surface, c, 0.22), borderRadius: BorderRadius.circular(6)),
        child: Text(text, style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w700, color: c)),
      );

  Widget _statsPanel(Pal p) {
    final s = stats;
    if (s == null) return const SizedBox.shrink();
    final n = (s['n'] as num).toInt();
    final byConf = ((s['by_conf'] as List?) ?? []).where((b) => (b['n'] as num) > 0).toList();
    return Panel(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('LAST ${s['days']} DAYS', style: TextStyle(color: p.muted, fontSize: 11, letterSpacing: 1)),
        const SizedBox(height: 6),
        Row(children: [
          Expanded(child: _big(p, _pct(s['win_rate']), 'TP1 before stop')),
          Expanded(child: _big(p, '$n', 'resolved')),
          Expanded(child: _big(p, _r(s['avg_r']), 'average')),
        ]),
        const SizedBox(height: 8),
        Text('Logged ${s['logged']}  -  open ${s['open']}  -  filled ${s['filled']}  -  never filled ${s['unfilled']}',
            style: TextStyle(color: p.muted, fontSize: 12)),
        if (byConf.isNotEmpty) ...[
          const SizedBox(height: 8),
          for (final b in byConf)
            Text('${b['label']}: ${b['n']} resolved, ${_pct(b['win_rate'])} TP1, ${_r(b['avg_r'])}',
                style: numStyle.copyWith(fontSize: 12.5)),
        ],
        if (n < 20)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text('Small sample: results are noisy until there are a few dozen resolved setups.',
                style: TextStyle(color: p.warn, fontSize: 12)),
          ),
      ]),
    );
  }

  Widget _big(Pal p, String v, String label) => Column(children: [
        Text(v, style: numStyle.copyWith(fontSize: 22, fontWeight: FontWeight.w800)),
        Text(label, style: TextStyle(color: p.muted, fontSize: 11.5)),
      ]);

  Widget _row(Pal p, Map<String, dynamic> e) {
    final (label, col) = _outcome(p, e);
    final long = e['dir'] == 'long';
    final res = e['r'];
    return Panel(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(
            child: Text('${e['name']}  ${styleLabels['${e['style']}'] ?? e['style']}',
                style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15)),
          ),
          Text(_ago((e['ts'] as num)), style: TextStyle(color: p.muted, fontSize: 12)),
        ]),
        const SizedBox(height: 6),
        Row(children: [
          Container(
            margin: const EdgeInsets.only(right: 6),
            child: _chip(p, '${e['dir']}'.toUpperCase(), long ? p.gain : p.loss),
          ),
          _chip(p, label, col),
          const Spacer(),
          Text('conf ${e['conf_raw']}${(e['news_pts'] as num) > 0 ? ' (news -${e['news_pts']})' : ''}',
              style: numStyle.copyWith(fontSize: 12.5, color: p.muted)),
        ]),
        const SizedBox(height: 6),
        Text('${e['poi']}  ${e['zone']}', style: numStyle.copyWith(fontSize: 12.5)),
        Text('Stop ${e['stop']}   TP1 ${e['tp1']} (${e['rr1']}R)', style: numStyle.copyWith(fontSize: 12.5)),
        if (res != null)
          Text('Result ${_r(res)}${e['mfe'] != null ? '   best move ${_r(e['mfe'])}' : ''}',
              style: numStyle.copyWith(fontSize: 12.5, fontWeight: FontWeight.w700, color: col)),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final p = context.pal;
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.all(12),
        children: [
          SegmentedButton<String>(
            segments: const [
              ButtonSegment(value: '', label: Text('All')),
              ButtonSegment(value: 'scalp', label: Text('Scalp')),
              ButtonSegment(value: 'intraday', label: Text('Intraday')),
              ButtonSegment(value: 'swing', label: Text('Swing')),
            ],
            selected: {style},
            onSelectionChanged: (s) {
              style = s.first;
              _load();
            },
          ),
          const SizedBox(height: 8),
          SegmentedButton<String>(
            segments: const [
              ButtonSegment(value: '', label: Text('All')),
              ButtonSegment(value: 'open', label: Text('Open')),
              ButtonSegment(value: 'closed', label: Text('Closed')),
            ],
            selected: {scope},
            onSelectionChanged: (s) {
              scope = s.first;
              _load();
            },
          ),
          const SizedBox(height: 8),
          if (loading) const LinearProgressIndicator(),
          if (err != null)
            Panel(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(err!, style: TextStyle(color: p.loss)),
                TextButton(onPressed: _load, child: const Text('Retry')),
              ]),
            ),
          _statsPanel(p),
          if (items.isEmpty && !loading && err == null)
            Padding(
              padding: const EdgeInsets.all(20),
              child: Text(
                'Nothing logged yet. Every 5 minutes the server records new setups and follows price to see whether '
                'each one reached TP1 or its stop. Results appear after a few hours.',
                textAlign: TextAlign.center,
                style: TextStyle(color: p.muted, height: 1.4),
              ),
            ),
          for (final e in items) _row(p, e as Map<String, dynamic>),
          const SizedBox(height: 8),
          Text(
            'Rules: a setup fills when price trades through its entry. If stop and TP1 sit in one candle the stop wins. '
            'Fees and slippage are ignored. Live forward results, not a backtest.',
            style: TextStyle(color: p.muted, fontSize: 12, height: 1.4),
          ),
        ],
      ),
    );
  }
}

// ------------------------------------------------------------------ calendar

class CalendarView extends StatefulWidget {
  const CalendarView({super.key});
  @override
  State<CalendarView> createState() => _CalendarViewState();
}

class _CalendarViewState extends State<CalendarView> with AutomaticKeepAliveClientMixin {
  static const _days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  static const _months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

  List items = [];
  List cur = [];
  String impact = 'high';
  String? err;
  String? feedErr;
  String? source;
  String tzLabel = '';
  String? notice;
  double updated = 0;
  bool loading = false;
  bool loaded = false;
  bool busy = false;
  Timer? tick;

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    if (ServerPrefs.I.section('calendar')['impact'] == 'medium') impact = 'medium';
    if (Api.ready) {
      _load(false);
    } else {
      err = 'Enter your API token in Settings to connect.';
    }
    tick = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted) setState(() {});
    });
  }

  @override
  void dispose() {
    tick?.cancel();
    super.dispose();
  }

  String _two(int n) => n.toString().padLeft(2, '0');

  String _clock(double ts) => TzClock.hm(ts);

  String _in(double ts) {
    final m = ((ts * 1000 - DateTime.now().millisecondsSinceEpoch) / 60000).round();
    if (m < -1) return 'released';
    if (m <= 0) return 'now';
    if (m < 60) return 'in $m min';
    final h = m ~/ 60;
    if (h < 24) return 'in ${h}h ${m % 60}m';
    return 'in ${h ~/ 24}d ${h % 24}h';
  }

  /// Live countdown for the hero card: mm:ss under an hour.
  String _countdown(double ts) {
    final s = ((ts * 1000 - DateTime.now().millisecondsSinceEpoch) / 1000).round();
    if (s <= 0) return 'NOW';
    if (s < 3600) return '${_two(s ~/ 60)}:${_two(s % 60)}';
    final h = s ~/ 3600;
    if (h < 24) return '${h}h ${_two((s % 3600) ~/ 60)}m';
    return '${h ~/ 24}d ${h % 24}h';
  }

  Future<void> _load(bool refresh) async {
    if (!Api.ready) {
      setState(() => err = 'Enter your API token in Settings to connect.');
      return;
    }
    setState(() {
      loading = true;
      err = null;
    });
    try {
      final d = await Api.get('/api/calendar', {
        'hours': '168',
        'impact': impact,
        if (refresh) 'refresh': '1',
      }) as Map<String, dynamic>;
      if (mounted) {
        setState(() {
          items = d['events'] as List;
          feedErr = d['error'] as String?;
          source = d['source'] as String?;
          tzLabel = '${d['tz'] ?? ''}';
          updated = (d['updated'] as num?)?.toDouble() ?? 0;
          cur = (d['currencies'] as List?) ?? [];
          loaded = true;
        });
      }
    } catch (e) {
      if (mounted) setState(() => err = '$e');
    }
    if (mounted) setState(() => loading = false);
  }

  Future<void> _testAlert() async {
    setState(() {
      busy = true;
      notice = null;
    });
    try {
      await Api.post('/api/calendar/test');
      final popup = LocalPrefs.I.allows('news', 'warning');
      notice = popup
          ? 'Test alert sent. A pop-up should appear in a moment, and a push notification if push is enabled.'
          : 'Test alert sent to the activity log and push. Pop-ups for news are switched off in Settings > Notifications.';
    } catch (e) {
      notice = 'Could not send the test alert: $e';
    }
    if (mounted) setState(() => busy = false);
  }

  Widget _hero(Pal p, double now) {
    Map<String, dynamic>? next;
    for (final raw in items) {
      final e = raw as Map<String, dynamic>;
      if ((e['ts'] as num).toDouble() > now - 30) {
        next = e;
        break;
      }
    }
    if (next == null) {
      return Panel(
        child: Row(children: [
          Icon(Icons.event_available, color: p.muted),
          const SizedBox(width: 10),
          Expanded(
            child: Text(loaded ? 'No matching events in the next 7 days.' : 'Loading the calendar...',
                style: TextStyle(color: p.muted)),
          ),
        ]),
      );
    }
    final ts = (next['ts'] as num).toDouble();
    final col = next['impact'] == 'high' ? p.loss : p.warn;
    final soon = ts - now < 3600;
    final aff = '${next['affects'] ?? ''}';
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: p.surface,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: soon ? col : p.outline, width: soon ? 1.8 : 1),
      ),
      child: Row(children: [
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('NEXT EVENT', style: TextStyle(color: p.muted, fontSize: 11, letterSpacing: 1)),
            const SizedBox(height: 4),
            Text('${next['currency']}  ${next['title']}', style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15.5)),
            const SizedBox(height: 2),
            Text('${next['local_time'] ?? _clock(ts)} $tzLabel${aff.isEmpty ? '' : '  -  affects $aff'}',
                style: TextStyle(color: p.muted, fontSize: 12.5)),
          ]),
        ),
        const SizedBox(width: 10),
        Text(_countdown(ts), style: numStyle.copyWith(fontSize: 26, fontWeight: FontWeight.w800, color: soon ? col : null)),
      ]),
    );
  }

  Widget _row(Pal p, Map<String, dynamic> e, DateTime d, double ts, double now) {
    final high = e['impact'] == 'high';
    final col = high ? p.loss : p.warn;
    final soon = ts - now < 3600 && ts - now > -600;
    final past = ts < now - 60;
    final fc = '${e['forecast'] ?? ''}';
    final pv = '${e['previous'] ?? ''}';
    final detail = [if (fc.isNotEmpty) 'Forecast $fc', if (pv.isNotEmpty) 'Previous $pv'].join('   ');
    final aff = '${e['affects'] ?? ''}';
    return Opacity(
      opacity: past ? 0.55 : 1,
      child: Container(
        margin: const EdgeInsets.only(bottom: 8),
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: p.surface,
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: soon ? col : p.outline, width: soon ? 1.6 : 1),
        ),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SizedBox(
            width: 52,
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('${e['local_time'] ?? '${_two(d.hour)}:${_two(d.minute)}'}', style: numStyle.copyWith(fontWeight: FontWeight.w700)),
              const SizedBox(height: 4),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
                decoration: BoxDecoration(
                  color: Color.lerp(p.surface, col, 0.25),
                  borderRadius: BorderRadius.circular(5),
                ),
                child: Text('${e['currency']}', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: col)),
              ),
            ]),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('${e['title']}', style: const TextStyle(fontWeight: FontWeight.w600)),
              if (detail.isNotEmpty) Text(detail, style: numStyle.copyWith(color: p.muted, fontSize: 12)),
              if (aff.isNotEmpty) Text('Affects: $aff', style: TextStyle(color: p.muted, fontSize: 12)),
            ]),
          ),
          Text(_in(ts), style: TextStyle(color: soon ? col : p.muted, fontWeight: FontWeight.w600, fontSize: 12.5)),
        ]),
      ),
    );
  }

  Widget _skeleton(Pal p) => Column(children: [
        for (var i = 0; i < 3; i++)
          Container(
            height: 62,
            margin: const EdgeInsets.only(bottom: 8),
            decoration: BoxDecoration(
              color: p.surface,
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: p.outline),
            ),
          ),
      ]);

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final p = context.pal;
    final now = DateTime.now().millisecondsSinceEpoch / 1000;
    final rows = <Widget>[];
    String lastDay = '';
    for (final raw in items) {
      final e = raw as Map<String, dynamic>;
      final ts = (e['ts'] as num).toDouble();
      final d = TzClock.dt(ts);
      final day = '${e['local_day'] ?? '${_days[d.weekday - 1]} ${d.day} ${_months[d.month - 1]}'}';
      if (day != lastDay) {
        lastDay = day;
        rows.add(Heading(day));
      }
      rows.add(_row(p, e, d, ts, now));
    }
    final backup = (source ?? '').toLowerCase().contains('backup');
    return RefreshIndicator(
      onRefresh: () => _load(true),
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.all(12),
        children: [
          _hero(p, now),
          SegmentedButton<String>(
            segments: const [
              ButtonSegment(value: 'high', label: Text('Red folder')),
              ButtonSegment(value: 'medium', label: Text('Red + orange')),
            ],
            selected: {impact},
            onSelectionChanged: (s) {
              setState(() => impact = s.first);
              _load(false);
            },
          ),
          const SizedBox(height: 8),
          Row(children: [
            Expanded(
              child: OutlinedButton.icon(
                onPressed: loading ? null : () => _load(true),
                icon: const Icon(Icons.refresh, size: 18),
                label: const Text('Refresh'),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: FilledButton.icon(
                onPressed: busy ? null : _testAlert,
                icon: const Icon(Icons.notifications_active_outlined, size: 18),
                label: const Text('Test alert'),
              ),
            ),
          ]),
          if (notice != null)
            Padding(padding: const EdgeInsets.only(top: 8), child: Text(notice!, style: TextStyle(color: p.gain, fontSize: 12.5))),
          const SizedBox(height: 6),
          Text('Tracking ${cur.isEmpty ? 'USD, EUR, GBP, JPY' : cur.join(', ')}. Gold follows USD. Times are in $tzLabel (change it in Settings > Time zone).',
              style: TextStyle(color: p.muted, fontSize: 12)),
          if (loading) const Padding(padding: EdgeInsets.only(top: 6), child: LinearProgressIndicator()),
          if (err != null)
            Panel(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(err!, style: TextStyle(color: p.loss)),
                TextButton(onPressed: () => _load(false), child: const Text('Retry')),
              ]),
            ),
          if (feedErr != null)
            Panel(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(
                  items.isEmpty
                      ? 'The calendar feed could not be reached from the server ($feedErr). Try again in a minute, '
                          'or open Settings > Diagnostics to see what failed.'
                      : 'Calendar feed problem ($feedErr). Showing the last data received.',
                  style: TextStyle(color: p.warn),
                ),
                TextButton(onPressed: () => _load(true), child: const Text('Retry now')),
              ]),
            ),
          if (backup)
            Text('Forex Factory is not reachable from the server, so a backup feed is shown. Times and impact levels may differ slightly.',
                style: TextStyle(color: p.warn, fontSize: 12)),
          const SizedBox(height: 6),
          if (loading && items.isEmpty) _skeleton(p),
          ...rows,
          const SizedBox(height: 12),
          Text(
            source == null
                ? 'Source: Forex Factory weekly feed.'
                : 'Source: $source${updated > 0 ? '. Updated ${_clock(updated)}' : ''}.',
            style: TextStyle(color: p.muted, fontSize: 12),
          ),
        ],
      ),
    );
  }
}
