export default function ProjectPage({ params }: { params: { id: string } }) {
  return (
    <main style={{ maxWidth: 720, margin: "60px auto" }}>
      <h1>方案展示</h1>
      <p style={{ color: "#646a73" }}>项目 ID：{params.id}（待实现）</p>
    </main>
  );
}
