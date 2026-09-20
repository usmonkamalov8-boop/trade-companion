import 'package:flutter/material.dart';
import '../events.dart';
import '../theme.dart';

class ActivityPage extends StatefulWidget {
  const ActivityPage({super.key});
  @override
  State<ActivityPage> createState() => _ActivityPageState();
}

class _ActivityPageState extends State<ActivityPage> {
  String filter = 'all';

  @override
  void initState() {
    super.initState();
    Toaster.logOpen = true;
    EventService.I.markRead();
    EventService.I.addListener(_onEvents);
  }

  @override
  void dispose() {
    Toaster.logOpen = false;
    EventService.I.removeListener(_onEvents);
    super.dispose();
  }

  void _onEvents() {
    if (!mounted) return;
    EventService.I.markRead();
    setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    final p = context.pal;
    final svc = EventService.I;
    final list = svc.events.reversed.where((e) => eventMatches(e, filter)).toList();
    return Scaffold(
      appBar: AppBar(
        title: const Text('Activity'),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 14),
            child: Row(children: [
              Icon(Icons.circle, size: 9, color: svc.connected ? p.gain : p.loss),
              const SizedBox(width: 6),
              Text(svc.connected ? 'Live' : 'Offline', style: TextStyle(color: p.muted, fontSize: 13)),
            ]),
          ),
        ],
      ),
      body: Column(children: [
        SizedBox(
          height: 52,
          child: ListView(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
            children: [
              for (final f in eventFilters.entries)
                Padding(
                  padding: const EdgeInsets.only(right: 8),
                  child: ChoiceChip(
                    label: Text(f.value),
                    selected: filter == f.key,
                    onSelected: (_) => setState(() => filter = f.key),
                  ),
                ),
            ],
          ),
        ),
        Expanded(
          child: RefreshIndicator(
            onRefresh: () async {
              EventService.I.restart();
              await Future.delayed(const Duration(milliseconds: 700));
            },
            child: list.isEmpty
                ? ListView(children: [
                    Padding(
                      padding: const EdgeInsets.all(32),
                      child: Text(
                        svc.connected
                            ? 'Nothing here yet. Halt, Resume, risk changes and position openings and closings will appear as they happen.'
                            : 'Waiting for the server. Check the connection in Settings.',
                        textAlign: TextAlign.center,
                        style: TextStyle(color: p.muted, height: 1.4),
                      ),
                    ),
                  ])
                : ListView.separated(
                    itemCount: list.length,
                    separatorBuilder: (_, __) => Divider(height: 1, color: p.outline),
                    itemBuilder: (_, i) => _row(p, list[i]),
                  ),
          ),
        ),
      ]),
    );
  }

  Widget _row(Pal p, AppEvent e) {
    final col = levelColor(p, e.level);
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 11),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Container(
          width: 34,
          height: 34,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            color: Color.lerp(p.bg, col, 0.16),
          ),
          child: Icon(kindIcon(e.kind), size: 18, color: col),
        ),
        const SizedBox(width: 12),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(e.title, style: const TextStyle(fontWeight: FontWeight.w600)),
            if (e.text.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 2),
                child: Text(e.text, style: TextStyle(color: p.muted, fontSize: 13, height: 1.3)),
              ),
          ]),
        ),
        const SizedBox(width: 10),
        Text(clockText(e.ts), style: numStyle.copyWith(color: p.muted, fontSize: 12)),
      ]),
    );
  }
}
