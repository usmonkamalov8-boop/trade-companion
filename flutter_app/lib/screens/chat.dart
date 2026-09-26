import 'package:flutter/material.dart';
import '../api.dart';
import '../theme.dart';

class ChatPage extends StatefulWidget {
  final String? initialQuestion;
  final Map<String, dynamic>? posContext;
  const ChatPage({super.key, this.initialQuestion, this.posContext});
  @override
  State<ChatPage> createState() => _ChatPageState();
}

class _ChatPageState extends State<ChatPage> {
  final msgs = <Map<String, String>>[];
  final ctl = TextEditingController();
  final sc = ScrollController();
  bool busy = false;
  static const quick = [
    'How are my positions?',
    'Best intraday setups',
    'Scalp setups now',
    'Swing setup gold',
    'Intraday setup BTC',
    'Order blocks ETH',
    'Top-down SOL',
    'Trade X-Ray BTC',
    'Why is gold confidence low?',
    'Journal stats',
    'Screener',
    'Market heatmap',
    'Backtest results',
    'Volume profile BTC',
    'Is forex open?',
    'Fib and premium discount EURUSD',
    'Red folder calendar',
    'Crypto briefing',
    'Forex and gold outlook',
    'How did the bot do this week?',
    'News sentiment',
    'Risk settings',
  ];

  // A handful of the quick list, surfaced as bigger suggestion cards on the empty state - the same list, just
  // a friendlier first impression than a single line of hint text.
  static const featured = [
    'How are my positions?',
    'Best intraday setups',
    'Crypto briefing',
    'Top-down SOL',
  ];

  @override
  void initState() {
    super.initState();
    if (widget.initialQuestion != null) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _send(widget.initialQuestion));
    }
  }

  @override
  void dispose() {
    ctl.dispose();
    sc.dispose();
    super.dispose();
  }

  void _down() => WidgetsBinding.instance.addPostFrameCallback((_) {
        if (sc.hasClients) sc.jumpTo(sc.position.maxScrollExtent);
      });

  Future<void> _send([String? preset]) async {
    final text = (preset ?? ctl.text).trim();
    if (text.isEmpty || busy) return;
    ctl.clear();
    setState(() {
      msgs.add({'role': 'user', 'content': text});
      msgs.add({'role': 'assistant', 'content': ''});
      busy = true;
    });
    _down();
    try {
      final history = msgs.sublist(0, msgs.length - 1).where((m) => m['content']!.isNotEmpty).toList();
      final body = <String, dynamic>{'messages': history};
      if (widget.posContext != null) body['context'] = {'position': widget.posContext};
      await for (final chunk in Api.stream('/api/chat', method: 'POST', body: body)) {
        if (!mounted) return;
        setState(() => msgs.last['content'] = msgs.last['content']! + chunk);
        _down();
      }
    } catch (e) {
      if (mounted) setState(() => msgs.last['content'] = '$e');
    }
    if (mounted) setState(() => busy = false);
  }

  @override
  Widget build(BuildContext context) {
    final p = context.pal;
    return Scaffold(
      appBar: AppBar(
        title: Row(mainAxisSize: MainAxisSize.min, children: [
          Icon(Icons.auto_awesome, size: 19, color: p.accent),
          const SizedBox(width: 8),
          const Text('Assistant'),
        ]),
        actions: [
          IconButton(
            onPressed: msgs.isEmpty ? null : () => setState(msgs.clear),
            icon: const Icon(Icons.delete_outline),
            tooltip: 'Clear conversation',
          ),
        ],
      ),
      body: Column(children: [
        Container(
          height: 46,
          decoration: BoxDecoration(border: Border(bottom: BorderSide(color: p.outline.withOpacity(0.5)))),
          child: ListView(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
            children: [
              for (final q in quick)
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 4),
                  child: ActionChip(
                    label: Text(q, style: const TextStyle(fontSize: 12.5)),
                    labelPadding: const EdgeInsets.symmetric(horizontal: 2),
                    backgroundColor: p.surface,
                    side: BorderSide(color: p.outline),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
                    onPressed: () => _send(q),
                  ),
                ),
            ],
          ),
        ),
        Expanded(
          child: msgs.isEmpty ? _EmptyState(p: p, featured: featured, onTap: _send) : _MessageList(msgs: msgs, sc: sc, p: p),
        ),
        SafeArea(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(10, 8, 10, 10),
            child: Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
              Expanded(
                child: Container(
                  constraints: const BoxConstraints(maxHeight: 120),
                  decoration: BoxDecoration(
                    color: p.surface,
                    borderRadius: BorderRadius.circular(22),
                    border: Border.all(color: p.outline),
                  ),
                  child: TextField(
                    controller: ctl,
                    minLines: 1,
                    maxLines: 4,
                    textInputAction: TextInputAction.send,
                    onSubmitted: (_) => _send(),
                    decoration: const InputDecoration(
                      hintText: 'Ask about your bot or the markets',
                      border: InputBorder.none,
                      contentPadding: EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                    ),
                  ),
                ),
              ),
              const SizedBox(width: 8),
              IconButton.filled(
                style: IconButton.styleFrom(backgroundColor: p.accent, foregroundColor: p.onAccent, minimumSize: const Size(46, 46)),
                onPressed: busy ? null : () => _send(),
                icon: busy
                    ? SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: p.onAccent))
                    : const Icon(Icons.arrow_upward),
              ),
            ]),
          ),
        ),
      ]),
    );
  }
}

class _EmptyState extends StatelessWidget {
  final Pal p;
  final List<String> featured;
  final void Function([String?]) onTap;
  const _EmptyState({required this.p, required this.featured, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          CircleAvatar(radius: 26, backgroundColor: p.accent.withOpacity(0.15), child: Icon(Icons.auto_awesome, color: p.accent, size: 26)),
          const SizedBox(height: 14),
          const Text('Ask me anything about your trading', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700), textAlign: TextAlign.center),
          const SizedBox(height: 6),
          Text(
            'Positions, bot performance, a pair like BTC or EUR/USD, gold, news, or sentiment.',
            textAlign: TextAlign.center,
            style: TextStyle(color: p.muted, fontSize: 13),
          ),
          const SizedBox(height: 20),
          for (final f in featured)
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: InkWell(
                borderRadius: BorderRadius.circular(12),
                onTap: () => onTap(f),
                child: Container(
                  width: 280,
                  padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                  decoration: BoxDecoration(color: p.surface, borderRadius: BorderRadius.circular(12), border: Border.all(color: p.outline)),
                  child: Row(children: [
                    Expanded(child: Text(f, style: const TextStyle(fontSize: 13.5))),
                    Icon(Icons.arrow_forward, size: 15, color: p.muted),
                  ]),
                ),
              ),
            ),
        ]),
      ),
    );
  }
}

class _MessageList extends StatelessWidget {
  final List<Map<String, String>> msgs;
  final ScrollController sc;
  final Pal p;
  const _MessageList({required this.msgs, required this.sc, required this.p});

  @override
  Widget build(BuildContext context) {
    return ListView.builder(
      controller: sc,
      padding: const EdgeInsets.all(12),
      itemCount: msgs.length,
      itemBuilder: (_, i) {
        final m = msgs[i];
        final me = m['role'] == 'user';
        final content = m['content']!;
        final thinking = !me && content.isEmpty;
        return Align(
          alignment: me ? Alignment.centerRight : Alignment.centerLeft,
          child: Row(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              if (!me) ...[
                CircleAvatar(radius: 12, backgroundColor: p.accent.withOpacity(0.15), child: Icon(Icons.auto_awesome, size: 12, color: p.accent)),
                const SizedBox(width: 6),
              ],
              Flexible(
                child: Container(
                  margin: const EdgeInsets.symmetric(vertical: 4),
                  padding: const EdgeInsets.symmetric(horizontal: 13, vertical: 11),
                  constraints: BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.78),
                  decoration: BoxDecoration(
                    color: me ? p.bubble : p.surface,
                    borderRadius: BorderRadius.circular(14),
                    border: Border.all(color: me ? p.bubbleBorder : p.outline),
                  ),
                  child: thinking
                      ? _ThinkingDots(color: p.muted)
                      : SelectableText(content, style: const TextStyle(height: 1.35)),
                ),
              ),
            ],
          ),
        );
      },
    );
  }
}

/// Three softly pulsing dots while waiting for the first token of a streamed reply - replaces the plain "..."
/// placeholder with something that reads as "working on it" rather than a possibly-stuck blank message.
class _ThinkingDots extends StatefulWidget {
  final Color color;
  const _ThinkingDots({required this.color});
  @override
  State<_ThinkingDots> createState() => _ThinkingDotsState();
}

class _ThinkingDotsState extends State<_ThinkingDots> with SingleTickerProviderStateMixin {
  late final AnimationController _c;
  @override
  void initState() {
    super.initState();
    _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 1100))..repeat();
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 34,
      height: 14,
      child: AnimatedBuilder(
        animation: _c,
        builder: (context, _) {
          return Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: List.generate(3, (i) {
              final t = (_c.value - i * 0.2) % 1.0;
              final scale = 0.5 + 0.5 * (t < 0.5 ? t * 2 : (1 - t) * 2);
              return Opacity(
                opacity: 0.4 + 0.6 * scale,
                child: Container(width: 6, height: 6, decoration: BoxDecoration(color: widget.color, shape: BoxShape.circle)),
              );
            }),
          );
        },
      ),
    );
  }
}
