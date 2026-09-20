import 'dart:async';
import 'package:flutter/material.dart';
import 'api.dart';
import 'prefs.dart';
import 'theme.dart';
import 'screens/activity.dart';

class AppEvent {
  final int id;
  final double ts;
  final String kind;
  final String level;
  final String title;
  final String text;
  AppEvent(this.id, this.ts, this.kind, this.level, this.title, this.text);

  factory AppEvent.fromJson(Map<String, dynamic> j) => AppEvent(
        (j['id'] as num).toInt(),
        (j['ts'] as num).toDouble(),
        '${j['kind']}',
        '${j['level']}',
        '${j['title']}',
        '${j['text'] ?? ''}',
      );
}

Color levelColor(Pal p, String level) {
  switch (level) {
    case 'success':
      return p.gain;
    case 'warning':
      return p.warn;
    case 'error':
      return p.loss;
    default:
      return p.accent;
  }
}

IconData kindIcon(String kind) {
  switch (kind) {
    case 'position':
      return Icons.swap_vert;
    case 'trade':
      return Icons.show_chart;
    case 'command':
      return Icons.power_settings_new;
    case 'risk':
      return Icons.tune;
    case 'profile':
      return Icons.toggle_on_outlined;
    case 'service':
      return Icons.memory;
    case 'news':
      return Icons.event_note;
    case 'warning':
      return Icons.warning_amber_rounded;
    default:
      return Icons.info_outline;
  }
}

const eventFilters = {'all': 'All', 'trades': 'Trades', 'news': 'News', 'bot': 'Bot', 'alerts': 'Alerts'};

bool eventMatches(AppEvent e, String f) {
  switch (f) {
    case 'trades':
      return e.kind == 'position' || e.kind == 'trade';
    case 'news':
      return e.kind == 'news';
    case 'bot':
      return const ['command', 'service', 'risk', 'profile', 'system'].contains(e.kind);
    case 'alerts':
      return e.level == 'warning' || e.level == 'error';
    default:
      return true;
  }
}

String _two(int n) => n.toString().padLeft(2, '0');

String clockText(double ts) {
  final d = DateTime.fromMillisecondsSinceEpoch((ts * 1000).round());
  final now = DateTime.now();
  final t = '${_two(d.hour)}:${_two(d.minute)}:${_two(d.second)}';
  if (d.year == now.year && d.month == now.month && d.day == now.day) return t;
  return '${_two(d.day)}/${_two(d.month)} $t';
}

/// Long-polls the backend so events arrive within a moment of happening.
class EventService extends ChangeNotifier {
  EventService._();
  static final EventService I = EventService._();

  final List<AppEvent> events = []; // oldest first
  int lastId = 0;
  int unread = 0;
  bool connected = false;
  bool _loaded = false;
  int _gen = 0;

  void restart() {
    _gen++;
    lastId = 0;
    unread = 0;
    events.clear();
    connected = false;
    _loaded = false;
    notifyListeners();
    _loop(_gen);
  }

  void markRead() {
    if (unread != 0) {
      unread = 0;
      notifyListeners();
    }
  }

  Future<void> _loop(int gen) async {
    while (gen == _gen) {
      if (!Api.ready) {
        await Future.delayed(const Duration(seconds: 3));
        continue;
      }
      try {
        final d = await Api.get('/api/events', {'since': '$lastId', 'wait': '20', 'limit': '100'})
            as Map<String, dynamic>;
        if (gen != _gen) return;
        final serverLast = (d['last_id'] as num).toInt();
        if (serverLast < lastId) {
          // the server log was reset: start over
          lastId = 0;
          events.clear();
          _loaded = false;
          continue;
        }
        final list = (d['events'] as List)
            .map((e) => AppEvent.fromJson(e as Map<String, dynamic>))
            .where((e) => e.id > lastId)
            .toList();
        final wasLoaded = _loaded;
        _loaded = true;
        connected = true;
        if (list.isNotEmpty) {
          events.addAll(list);
          if (events.length > 500) events.removeRange(0, events.length - 500);
          lastId = list.last.id;
          if (wasLoaded) {
            unread += list.length;
            final now = DateTime.now().millisecondsSinceEpoch / 1000;
            Toaster.show(list.where((e) => now - e.ts < 180 && LocalPrefs.I.allows(e.kind, e.level)).toList());
          }
        }
        notifyListeners();
      } catch (e) {
        if (gen != _gen) return;
        if (connected) {
          connected = false;
          notifyListeners();
        }
        await Future.delayed(const Duration(seconds: 4));
      }
    }
  }
}

/// Pop-up banners shown on top of every screen.
class Toaster {
  static final navKey = GlobalKey<NavigatorState>();
  static final List<AppEvent> _queue = [];
  static OverlayEntry? _entry;
  static Timer? _timer;
  static bool logOpen = false;

  static void show(List<AppEvent> evs) {
    if (evs.isEmpty) return;
    _queue.addAll(evs.length > 3 ? evs.sublist(evs.length - 3) : evs);
    if (_queue.length > 4) _queue.removeRange(0, _queue.length - 4);
    _next();
  }

  static void _next() {
    if (_entry != null || _queue.isEmpty) return;
    final overlay = navKey.currentState?.overlay;
    if (overlay == null) {
      _queue.clear();
      return;
    }
    final e = _queue.removeAt(0);
    late OverlayEntry entry;
    entry = OverlayEntry(builder: (_) => _ToastView(event: e, onClose: () => _dismiss(entry)));
    _entry = entry;
    overlay.insert(entry);
    _timer = Timer(const Duration(seconds: 4), () => _dismiss(entry));
  }

  static void _dismiss(OverlayEntry entry) {
    if (_entry != entry) return;
    _timer?.cancel();
    entry.remove();
    _entry = null;
    Future.delayed(const Duration(milliseconds: 250), _next);
  }

  static void openLog() {
    if (logOpen) return;
    navKey.currentState?.push(MaterialPageRoute(builder: (_) => const ActivityPage()));
  }
}

class _ToastView extends StatelessWidget {
  final AppEvent event;
  final VoidCallback onClose;
  const _ToastView({required this.event, required this.onClose});

  @override
  Widget build(BuildContext context) {
    final p = context.pal;
    final col = levelColor(p, event.level);
    return Positioned(
      top: 0,
      left: 0,
      right: 0,
      child: SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(12, 8, 12, 0),
          child: TweenAnimationBuilder<double>(
            tween: Tween(begin: 0, end: 1),
            duration: const Duration(milliseconds: 220),
            curve: Curves.easeOut,
            builder: (c, v, child) => Opacity(
              opacity: v,
              child: Transform.translate(offset: Offset(0, (v - 1) * 24), child: child),
            ),
            child: Material(
              color: p.surface,
              elevation: 6,
              borderRadius: BorderRadius.circular(12),
              child: InkWell(
                borderRadius: BorderRadius.circular(12),
                onTap: () {
                  onClose();
                  Toaster.openLog();
                },
                child: Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: col),
                  ),
                  child: Row(children: [
                    Icon(kindIcon(event.kind), color: col, size: 22),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
                        Text(event.title, style: const TextStyle(fontWeight: FontWeight.w700)),
                        if (event.text.isNotEmpty)
                          Text(event.text,
                              maxLines: 2,
                              overflow: TextOverflow.ellipsis,
                              style: TextStyle(color: p.muted, fontSize: 12.5)),
                      ]),
                    ),
                  ]),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
