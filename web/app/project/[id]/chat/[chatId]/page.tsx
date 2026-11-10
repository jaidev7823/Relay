import ProjectView from "../../ProjectView";

export default async function ChatPage({
  params,
}: {
  params: Promise<{ id: string; chatId: string }>;
}) {
  const { id, chatId } = await params;
  return <ProjectView projectId={id} chatId={chatId} />;
}
