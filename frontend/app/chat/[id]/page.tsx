export default function ChatPage({ params }: { params: { id: string } }) {
  return (
    <main style={{ maxWidth: 720, margin: "60px auto" }}>
      <h1>诊断对话</h1>
      <p style={{ color: "#646a73" }}>会话 ID：{params.id}（待实现）</p>
    </main>
  );
}
