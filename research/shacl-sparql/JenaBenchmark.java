import java.util.Locale;

import org.apache.jena.graph.Graph;
import org.apache.jena.riot.RDFDataMgr;
import org.apache.jena.shacl.ShaclValidator;
import org.apache.jena.shacl.Shapes;
import org.apache.jena.shacl.ValidationReport;

/** Measure Jena data loading, shapes loading, and SHACL validation separately. */
public final class JenaBenchmark {
    private static double seconds(long start, long end) {
        return (end - start) / 1_000_000_000.0;
    }

    public static void main(String[] args) {
        if (args.length != 2) {
            throw new IllegalArgumentException("usage: JenaBenchmark DATA.nt SHAPES.ttl");
        }

        long started = System.nanoTime();
        Graph data = RDFDataMgr.loadGraph(args[0]);
        long dataLoaded = System.nanoTime();
        Graph shapesGraph = RDFDataMgr.loadGraph(args[1]);
        Shapes shapes = ShaclValidator.get().parse(shapesGraph);
        long shapesLoaded = System.nanoTime();
        ValidationReport report = ShaclValidator.get().validate(shapes, data);
        long finished = System.nanoTime();

        System.out.printf(
            Locale.ROOT,
            "{\"engine\":\"jena\",\"conforms\":%s,\"results\":%d,"
                + "\"data_triples\":%d,\"data_load_seconds\":%.9f,"
                + "\"shapes_load_seconds\":%.9f,\"validation_seconds\":%.9f,"
                + "\"inside_process_seconds\":%.9f}%n",
            report.conforms(),
            report.getEntries().size(),
            data.size(),
            seconds(started, dataLoaded),
            seconds(dataLoaded, shapesLoaded),
            seconds(shapesLoaded, finished),
            seconds(started, finished)
        );
    }
}
