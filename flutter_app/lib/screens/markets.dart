import 'dart:async';
import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';
import '../api.dart';
import '../theme.dart';

class MarketsPage extends StatelessWidget {
  const MarketsPage({super.key});
  @override
  Widget build(BuildContext context) => DefaultTabController(
        length: 4,
        child: Scaffold(
          appBar: AppBar(
            title: const Text('Markets'),
            bottom: const TabBar(isScrollable: true, tabs: [
              Tab(text: 'Crypto'),
              Tab(text: 'Forex and gold'),
              Tab(text: 'Calendar'),
              Tab(text: 'News'),
            ]),
          ),
          body: const TabBarView(children: [
            MarketView('crypto'),
            MarketView('forex'),
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
          Text('${r['price_str']}', style: numStyle.copyWith(fontWeight: FontWeight.w600)),
        ]),
        const SizedBox(height: 4),
        Row(children: [
          Text('${r['bias']} (${signed(score, 0)})',
              style: TextStyle(color: biasColor(p, score), fontWeight: FontWeight.w600)),
          const SizedBox(width: 10),
          Text('${signed(chg)}%', style: numStyle.copyWith(color: chg >= 0 ? p.gain : p.loss)),
          const Spacer(),
          for (final k in ['1h', '4h', '1d'])
            if (tf[k] != null) _tfTag(p, k, (tf[k]['score'] as num).toInt()),
        ]),
        const SizedBox(height: 4),
        Text('RSI ${r['rsi'] ?? '-'}   support ${r['support_str']}   resistance ${r['resistance_str']}',
            style: numStyle.copyWith(color: p.muted, fontSize: 12)),
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
  double updated = 0;
  bool loading = false;
  Timer? tick;

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    if (Api.ready) _load(false);
    tick = Timer.periodic(const Duration(seconds: 30), (_) {
      if (mounted) setState(() {});
    });
  }

  @override
  void dispose() {
    tick?.cancel();
    super.dispose();
  }

  String _two(int n) => n.toString().padLeft(2, '0');

  String _clock(double ts) {
    final d = DateTime.fromMillisecondsSinceEpoch((ts * 1000).round());
    return '${_two(d.hour)}:${_two(d.minute)}';
  }

  String _in(double ts) {
    final m = ((ts * 1000 - DateTime.now().millisecondsSinceEpoch) / 60000).round();
    if (m < -1) return 'released';
    if (m <= 0) return 'now';
    if (m < 60) return 'in $m min';
    final h = m ~/ 60;
    if (h < 24) return 'in ${h}h ${m % 60}m';
    return 'in ${h ~/ 24}d ${h % 24}h';
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
          updated = (d['updated'] as num?)?.toDouble() ?? 0;
          cur = (d['currencies'] as List?) ?? [];
        });
      }
    } catch (e) {
      if (mounted) setState(() => err = '$e');
    }
    if (mounted) setState(() => loading = false);
  }

  Future<void> _testAlert() async {
    try {
      await Api.post('/api/calendar/test');
    } catch (e) {
      if (mounted) setState(() => err = '$e');
    }
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
              Text('${_two(d.hour)}:${_two(d.minute)}', style: numStyle.copyWith(fontWeight: FontWeight.w700)),
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
      final d = DateTime.fromMillisecondsSinceEpoch((ts * 1000).round());
      final day = '${_days[d.weekday - 1]} ${d.day} ${_months[d.month - 1]}';
      if (day != lastDay) {
        lastDay = day;
        rows.add(Heading(day));
      }
      rows.add(_row(p, e, d, ts, now));
    }
    return RefreshIndicator(
      onRefresh: () => _load(true),
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.all(12),
        children: [
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
          Text('Tracking ${cur.join(', ')}. Gold follows USD. Times use your phone time zone.',
              style: TextStyle(color: p.muted, fontSize: 12)),
          if (loading) const LinearProgressIndicator(),
          if (err != null) Panel(child: Text(err!, style: TextStyle(color: p.loss))),
          if (feedErr != null)
            Panel(
              child: Text('Calendar feed problem: $feedErr. Showing the last data received.',
                  style: TextStyle(color: p.warn)),
            ),
          if (items.isEmpty && !loading && err == null)
            Padding(
              padding: const EdgeInsets.all(24),
              child: Text('No matching events in the next 7 days.',
                  textAlign: TextAlign.center, style: TextStyle(color: p.muted)),
            ),
          ...rows,
          const SizedBox(height: 12),
          Row(children: [
            Expanded(
              child: Text(
                updated > 0 ? 'Source: Forex Factory weekly feed. Updated ${_clock(updated)}.' : 'Source: Forex Factory weekly feed.',
                style: TextStyle(color: p.muted, fontSize: 12),
              ),
            ),
            TextButton(onPressed: _testAlert, child: const Text('Test alert')),
          ]),
        ],
      ),
    );
  }
}
