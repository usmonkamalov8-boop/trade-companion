import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';
import '../api.dart';
import '../theme.dart';

class MarketsPage extends StatelessWidget {
  const MarketsPage({super.key});
  @override
  Widget build(BuildContext context) => DefaultTabController(
        length: 3,
        child: Scaffold(
          appBar: AppBar(
            title: const Text('Markets'),
            bottom: const TabBar(tabs: [
              Tab(text: 'Crypto'),
              Tab(text: 'Forex and gold'),
              Tab(text: 'News'),
            ]),
          ),
          body: const TabBarView(children: [
            MarketView('crypto'),
            MarketView('forex'),
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

  Widget _tfTag(String k, int score) => Container(
        margin: const EdgeInsets.only(left: 4),
        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(6),
          border: Border.all(color: biasColor(score)),
        ),
        child: Text(k.toUpperCase(), style: TextStyle(fontSize: 11, color: biasColor(score))),
      );

  Widget _row(Map<String, dynamic> r) {
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
              style: TextStyle(color: biasColor(score), fontWeight: FontWeight.w600)),
          const SizedBox(width: 10),
          Text('${signed(chg)}%', style: numStyle.copyWith(color: chg >= 0 ? C.gain : C.loss)),
          const Spacer(),
          for (final k in ['1h', '4h', '1d'])
            if (tf[k] != null) _tfTag(k, (tf[k]['score'] as num).toInt()),
        ]),
        const SizedBox(height: 4),
        Text('RSI ${r['rsi'] ?? '-'}   support ${r['support_str']}   resistance ${r['resistance_str']}',
            style: numStyle.copyWith(color: C.muted, fontSize: 12)),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    return RefreshIndicator(
      onRefresh: _reload,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.all(12),
        children: [
          if (busy) const LinearProgressIndicator(),
          if (err != null) Panel(child: Text(err!, style: const TextStyle(color: C.loss))),
          for (final r in rows) _row(r as Map<String, dynamic>),
          if (text.isNotEmpty) const Heading('Briefing'),
          if (text.isNotEmpty)
            Panel(child: SelectableText(text, style: const TextStyle(height: 1.4))),
          const SizedBox(height: 12),
          const Text('Pull down to refresh. Colored tags show 1H, 4H and 1D trend.',
              style: TextStyle(color: C.muted, fontSize: 12)),
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
            separatorBuilder: (_, __) => const Divider(height: 1, color: C.outline),
            itemBuilder: (_, i) {
              if (items.isEmpty) {
                return Padding(
                  padding: const EdgeInsets.all(16),
                  child: Text(err ?? (loading ? '' : 'No headlines yet. Pull down to refresh.'),
                      style: TextStyle(color: err != null ? C.loss : C.muted)),
                );
              }
              final n = items[i] as Map<String, dynamic>;
              final sent = (n['sent'] as num).toInt();
              return ListTile(
                leading: Icon(
                  sent > 0 ? Icons.arrow_upward : (sent < 0 ? Icons.arrow_downward : Icons.remove),
                  color: sent > 0 ? C.gain : (sent < 0 ? C.loss : C.muted),
                  size: 20,
                ),
                title: Text('${n['title']}', style: const TextStyle(fontSize: 14.5)),
                subtitle: Text('${n['source']}', style: const TextStyle(color: C.muted, fontSize: 12)),
                onTap: () => launchUrl(Uri.parse('${n['link']}'), mode: LaunchMode.externalApplication),
              );
            },
          ),
        ),
      ),
    ]);
  }
}
