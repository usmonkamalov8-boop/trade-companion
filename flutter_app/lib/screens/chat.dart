import 'package:flutter/material.dart';
import '../api.dart';
import '../theme.dart';

class ChatPage extends StatefulWidget {
  const ChatPage({super.key});
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
    'How did the bot do this week?',
    'Crypto briefing',
    'Forex and gold outlook',
    'Best setups now',
    'News sentiment',
    'Risk settings',
  ];

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
      await for (final chunk in Api.stream('/api/chat', method: 'POST', body: {'messages': history})) {
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
      appBar: AppBar(title: const Text('Assistant'), actions: [
        IconButton(onPressed: () => setState(msgs.clear), icon: const Icon(Icons.delete_outline)),
      ]),
      body: Column(children: [
        SizedBox(
          height: 48,
          child: ListView(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.symmetric(horizontal: 8),
            children: [
              for (final q in quick)
                Padding(
                  padding: const EdgeInsets.all(4),
                  child: ActionChip(label: Text(q), onPressed: () => _send(q)),
                ),
            ],
          ),
        ),
        Expanded(
          child: msgs.isEmpty
              ? Center(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Text(
                      'Ask about your positions, bot performance, a pair like BTC or EUR/USD, gold, news or sentiment.',
                      textAlign: TextAlign.center,
                      style: TextStyle(color: p.muted),
                    ),
                  ),
                )
              : ListView.builder(
                  controller: sc,
                  padding: const EdgeInsets.all(12),
                  itemCount: msgs.length,
                  itemBuilder: (_, i) {
                    final m = msgs[i];
                    final me = m['role'] == 'user';
                    return Align(
                      alignment: me ? Alignment.centerRight : Alignment.centerLeft,
                      child: Container(
                        margin: const EdgeInsets.symmetric(vertical: 4),
                        padding: const EdgeInsets.all(11),
                        constraints: BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.9),
                        decoration: BoxDecoration(
                          color: me ? p.bubble : p.surface,
                          borderRadius: BorderRadius.circular(10),
                          border: Border.all(color: me ? p.bubbleBorder : p.outline),
                        ),
                        child: SelectableText(
                          m['content']!.isEmpty ? '...' : m['content']!,
                          style: const TextStyle(height: 1.35),
                        ),
                      ),
                    );
                  },
                ),
        ),
        SafeArea(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(8, 4, 8, 8),
            child: Row(children: [
              Expanded(
                child: TextField(
                  controller: ctl,
                  minLines: 1,
                  maxLines: 4,
                  textInputAction: TextInputAction.send,
                  onSubmitted: (_) => _send(),
                  decoration: const InputDecoration(
                    hintText: 'Ask about your bot or the markets',
                    border: OutlineInputBorder(),
                  ),
                ),
              ),
              const SizedBox(width: 6),
              IconButton.filled(onPressed: busy ? null : () => _send(), icon: const Icon(Icons.send)),
            ]),
          ),
        ),
      ]),
    );
  }
}
