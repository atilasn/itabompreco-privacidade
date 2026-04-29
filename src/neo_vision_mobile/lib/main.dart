import 'package:flutter/material.dart';

void main() {
  runApp(const NeoVisionApp());
}

class NeoVisionApp extends StatelessWidget {
  const NeoVisionApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'NeoVision AI',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF1E3A5F)),
        useMaterial3: true,
      ),
      home: const HomeScreen(),
    );
  }
}

class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('NeoVision AI'),
        centerTitle: true,
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: const [
          Text(
            'Monitoramento, reconhecimento facial e automação.',
            style: TextStyle(fontSize: 16),
          ),
          SizedBox(height: 20),
          _ModuleTile(
            icon: Icons.notifications_active_outlined,
            title: 'Alertas',
            subtitle: 'Push quando houver evento (integrar FCM).',
          ),
          _ModuleTile(
            icon: Icons.door_sliding_outlined,
            title: 'Portão',
            subtitle: 'POST /automation/gate/open no serviço local.',
          ),
          _ModuleTile(
            icon: Icons.videocam_outlined,
            title: 'Câmeras',
            subtitle: 'Visualização ao vivo (RTSP/WebRTC em fase posterior).',
          ),
        ],
      ),
    );
  }
}

class _ModuleTile extends StatelessWidget {
  const _ModuleTile({
    required this.icon,
    required this.title,
    required this.subtitle,
  });

  final IconData icon;
  final String title;
  final String subtitle;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: ListTile(
        leading: Icon(icon, size: 32),
        title: Text(title, style: const TextStyle(fontWeight: FontWeight.w600)),
        subtitle: Text(subtitle),
        onTap: () {},
      ),
    );
  }
}
